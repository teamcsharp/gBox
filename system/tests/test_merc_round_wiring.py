"""Icon-panel choices reach native menus and hold only the intended round boundary."""
import random
import struct
import uuid
from types import SimpleNamespace

import pytest

from gbox.mercs import round_controls as C
from gbox.mercs.titles import re5_switch as R5, re6_switch as R6


def control(tmp_path, title='re4', mode='pool'):
    c = C.Controls(title, 'owned-session', path=tmp_path / 'stages.json', rng=random.Random(3))
    c.configured = True
    c.observed(1, 0)
    if mode in ('once', 'loop'):
        out = c.command({'op': 'replay', 'request_id': str(uuid.uuid4()), 'mode': mode, 'enabled': True})
        assert out['receipt']['status'] in ('queued', 'applied')
    return c


class Memory:
    def __init__(self, c):
        self.adapter = SimpleNamespace(_merc_round_controls=c)
        self.data = {}

    def rd(self, at, n):
        raw = self.data.get(at)
        if raw is None:
            raise OSError('native page unavailable')
        return raw[:n]


def test_re6_excluded_or_unreadable_stage_never_uses_global_fallback(tmp_path, monkeypatch):
    c = control(tmp_path, 're6')
    c.rows = [dict(row, enabled=row['id'] == 2, weight=100 if row['id'] == 2 else 0) for row in c.rows]
    m = Memory(c)
    monkeypatch.setattr(R6, 'PICK', R6._Pick())
    monkeypatch.setattr(R6, 'STAGE_TARGET', 0)
    for raw in (None, b'\x01', struct.pack('<I', 1 << 0), struct.pack('<I', 0)):
        m.data = {} if raw is None else {100 + R6.STAGE_UNLOCKED: raw}
        target = R6.stage_target(m, 100)
        assert target is None
        assert R6.step({'where': 'select_stage', 'cursor': 0, 'target': target}) is None
    m.data = {100 + R6.STAGE_UNLOCKED: struct.pack('<I', (1 << 0) | (1 << 2))}
    assert R6.stage_target(m, 100) == 2


def test_re6_unreadable_or_insufficient_character_list_waits(tmp_path, monkeypatch):
    c = control(tmp_path, 're6', 'once')
    m = Memory(c)
    monkeypatch.setattr(R6, 'PICK', R6._Pick())
    for n, ids in ((None, None), (17, None), (2, b'\x00'), (1, struct.pack('<i', 0))):
        m.data = {} if n is None else {100 + R6.PLAYER_COUNT: struct.pack('<i', n)}
        if ids is not None:
            m.data[100 + R6.PLAYER_IDS] = ids
        target = R6.player_target(m, 100)
        assert target is None
        assert R6.step({'where': 'select_player', 'cursor': 0, 'target': target}) is None
    m.data = {100 + R6.PLAYER_COUNT: struct.pack('<i', 2), 100 + R6.PLAYER_IDS: struct.pack('<2i', 0, 3)}
    assert R6.player_target(m, 100) == 1  # native cursor index, not character id


def test_re6_playing_identity_comes_from_actual_game_not_global_requested_pick(tmp_path, monkeypatch):
    c = control(tmp_path, 're6', 'once')
    m = Memory(c)
    pick = R6._Pick()
    pick.stage, pick.character, pick.costume = 1, 3, 0
    monkeypatch.setattr(R6, 'PICK', pick)
    monkeypatch.setattr(R6, '_count_round', lambda *args: None)
    monkeypatch.setattr(R6, 'module_base', lambda m: 1000)
    monkeypatch.setattr(R6, 'ui_units', lambda m, base: {'uIdMerceUI': 50})
    monkeypatch.setattr(R6, 'snapshot', lambda m: {'player': {'hp': 100}, 'mercenaries_phase': R6.PHASE_PLAYING})
    monkeypatch.setattr(R6, 'game_man', lambda m, base: 2000)
    m.data = {2000 + R6.GM_STAGE: struct.pack('<i', 1), 2000 + R6.GM_COSTUME: struct.pack('<i', 0)}
    assert R6.screen(m)['where'] == 'playing'
    assert c.once and c.current_character == 0  # desired character 3 did not load
    m.data[2000 + R6.GM_COSTUME] = struct.pack('<i', 12)
    R6.screen(m)
    assert c.once is None and c.current_character == 3
    c.stage = 4
    R6.screen(m)
    assert c.stage == 4  # repeated native observations do not redraw the next selection


def test_re6_managed_replay_declines_same_character_continue(tmp_path, monkeypatch):
    m = Memory(control(tmp_path, 're6', 'loop'))
    monkeypatch.setattr(R6, 'REPLAY_ON_DEATH', True)
    m.data = {100 + R6.CONTINUE_MENU: struct.pack('<Q', 0x5D00001000),
              100 + R6.CONTINUE_CURSOR: struct.pack('<i', 0)}
    assert R6.continue_prompt(m, 100)['target'] == R6.CONTINUE_NO


def test_re5_replay_changes_character_family_not_costume(tmp_path):
    c = control(tmp_path, 're5')
    c.observed(1, 8)
    c.command({'op': 'replay', 'request_id': str(uuid.uuid4()), 'mode': 'once'})
    assert c.choose_character([8, 9]) is None
    assert c.choose_character([8, 9, 6]) == 6
    c.observed(1, 9)
    assert c.once is not None
    c.observed(1, 6)
    assert c.once is None


def test_re5_confirmation_is_adapter_local_and_not_global_cycle(tmp_path, monkeypatch):
    c = control(tmp_path, 're5', 'once')
    m = Memory(c)
    monkeypatch.setattr(R5, 'own_screen', lambda snap: 'playing')
    monkeypatch.setattr(R5.RE5Switch, '_mods', lambda *args: None)
    monkeypatch.setattr(R5.RE5Switch, '_cycle_started', lambda *args: None)
    driver = R5.RE5Switch(clock=lambda: 1)
    driver.screen(m, {'timer': 120})
    assert c.once is not None
    c.menu_pressed({'where': 'select_stage', 'cursor': 1, 'target': 1}, 'a')
    c.menu_pressed({'where': 'select_player', 'cursor': 3, 'target': 3}, 'a')
    driver.screen(m, {'timer': 119})
    assert c.once is None and c.current_character == 3


@pytest.mark.parametrize('rejected', [False, {'held': True}, {'stopped': True}, {'sent': 0}])
def test_re5_rejected_menu_delivery_cannot_confirm_a_replay(tmp_path, rejected):
    from gbox.mercs_bot import Boot
    c = control(tmp_path, 're5', 'once')
    now = [0.0]
    menus = SimpleNamespace(step=lambda scr: 'a')
    boot = Boot(menus, Memory(c), lambda events: rejected, clock=lambda: now[0],
                sleep=lambda dt: now.__setitem__(0, now[0] + dt))
    for where, cursor in (('select_stage', 1), ('select_player', 3)):
        scr = {'where': where, 'cursor': cursor, 'target': cursor}
        boot.nav.tick(scr)
        now[0] += 1
        boot.nav.tick(scr)
        now[0] += 2
    c.confirmed_round()
    assert c.once is not None and c.confirmed == {}


def test_re4_native_selects_override_old_requests_and_death_answers_no(tmp_path, monkeypatch):
    from gbox import re4_menus as R
    from tests.test_re4_menus import FakeRE4
    c = control(tmp_path, 're4', 'once')
    monkeypatch.setattr(R, 'REQUESTS', {'test': {'player': 0, 'stage': 0}})
    monkeypatch.setattr(R, 'ASKED', {'test': {'player': 0, 'stage': 0}})
    selection = R.RandomSelections(random.Random(2), key='test', controls=c)
    game = FakeRE4(routine=6, step=8)
    assert selection.screen(game)['target'] != 0
    game.tw(6, 12)
    assert selection.screen(game)['target'] == 1
    assert selection.step({'where': 'dead'}) == R.DPAD['right']
    assert selection.step({'where': 'dead'}) == 'a'


def test_re4_managed_preferences_cannot_be_bypassed_by_cached_round(tmp_path):
    from gbox.re4_merc_bot import InstantRounds
    instant = InstantRounds.__new__(InstantRounds)
    instant.ad = SimpleNamespace(_merc_round_controls=control(tmp_path))
    instant.stats = {}
    instant.lib = SimpleNamespace(tripped=lambda: pytest.fail('cached library must not be used'))
    kind, detail = instant.decide((0x400, 'Leon'), 'dead')
    assert kind is None and 'native character and stage menus' in detail


@pytest.mark.parametrize('mode,held', [('pool', False), ('once', True), ('loop', True)])
def test_engine_boundary_held_only_for_pending_replay_or_loop(tmp_path, monkeypatch, mode, held):
    from gbox import mercmode
    from gbox.mercs import engine, lessons
    from tests.test_mercs_engine import Clock
    c = control(tmp_path, mode=mode)
    monkeypatch.setattr(lessons, 'ROOT', tmp_path / 'lessons')
    calls = []
    monkeypatch.setattr(mercmode, 'publish_boundary', lambda sink, body, stats: calls.append(body))
    clk, stats = Clock(), {}

    class Driver:
        prompt_unknown = (LookupError,)
        def snapshot(self, m): return {'player': {'hp': 1000}, 'timer': 0 if clk.t > .1 else 2, 'kills': 0}
        def screen(self, m, snap): return 'results' if snap['timer'] == 0 else 'playing'
        def prompt_source(self, m, stats): return None
        def prompt_keys(self, button): return []
        def progress(self, snap): return {'timer': snap['timer']}
        def result_ready(self, snap, now): return True

    brain = SimpleNamespace(tick=lambda snap: {'hold': set()}, save=lambda: None)
    engine.play_round({'map_id': 'G4BE08'}, Memory(c), lambda rows: None, lambda: clk.t > 3, stats,
                      driver=Driver(), brain=brain, clock=clk, sleep=clk.sleep, learn_dir=tmp_path)
    assert len(calls) == (0 if held else 1)
    assert stats['icon_panel_holds_title'] is held


@pytest.mark.parametrize('mode,held', [('pool', False), ('once', True), ('loop', True)])
def test_legacy_re4_boundary_held_only_for_pending_replay_or_loop(tmp_path, mode, held):
    from gbox import re4_merc_bot as B
    from tests.test_re4_merc_bot import world
    c = control(tmp_path, mode=mode)
    game = world([], timer_s=2)
    game.adapter = SimpleNamespace(_merc_round_controls=c)
    now, calls, stats = [0.0], [], {}
    def sleep(dt):
        now[0] += dt
        if now[0] > .1:
            game.put(B.MERC_TIMER, '>I', 0)
    B.play(None, lambda events: None, lambda: now[0] > 2, m=game, sleep=sleep, clock=lambda: now[0],
           stats=stats, learn_dir=tmp_path, hooks=lambda: [], ram_prompt=False,
           round_boundary=lambda body, live: calls.append(body))
    assert len(calls) == (0 if held else 1)
    assert stats['icon_panel_holds_title'] is held


def test_saved_pool_reaches_an_existing_unconfigured_control_before_status_poll(tmp_path):
    first = C.Controls('re4', 'one', path=tmp_path / 'shared.json')
    second = C.Controls('re4', 'two', path=tmp_path / 'shared.json')
    assert second.managed is False
    first.command({'op': 'stages', 'request_id': str(uuid.uuid4()), 'stages': [
        dict(row, enabled=row['id'] == 2, weight=100 if row['id'] == 2 else 0) for row in first.rows]})
    assert second.managed is True
    assert second.choose_stage(range(4)) == 2
    assert second.once is None and second.loop_stage is None


def test_acknowledged_stage_mirror_is_exact_host_title_and_session(tmp_path):
    from tests.test_mercmode import Store
    store = Store()
    store.put('session', 'owned-session', {'worker_id': 'worker'})
    store.put('worker', 'worker', {'name': 'Test PC'})
    c = control(tmp_path)
    c.rows = [dict(row, enabled=row['id'] == 2, weight=100 if row['id'] == 2 else 0) for row in c.rows]
    report = c.status()
    C.remember_preferences(store, 'different-session', report)
    assert store.get('merc-stage-rotation', 'Test PC:re4') is None
    C.remember_preferences(store, 'owned-session', report | {'configured': False})
    assert store.get('merc-stage-rotation', 'Test PC:re4') is None
    C.remember_preferences(store, 'owned-session', report)
    assert C.warm_stage_allowed(store, 'Test PC', 're4', {'stage_index': 2})
    assert C.warm_stage_allowed(store, 'Test PC', 're4', {'stage': c.names[2]})
    for prepared in ({'stage_index': 0}, {'stage': c.names[0]}, {}, None, {'stage_index': True}):
        assert C.warm_stage_allowed(store, 'Test PC', 're4', prepared) is False
    assert C.warm_stage_allowed(store, 'Other PC', 're4', {'stage_index': 0})
    assert C.warm_stage_allowed(store, 'Test PC', 're5', {'stage_index': 0})


def test_excluded_prepared_round_is_stopped_and_never_resumed(monkeypatch):
    from gbox import mercmode
    from tests.test_mercmode import rig
    store, worker, saver, calls, now, tick = rig()
    store.put('merc-stage-rotation', worker['name'] + ':re4', {'stages': [
        {'id': 0, 'enabled': False, 'weight': 0}, {'id': 1, 'enabled': True, 'weight': 100}]})
    row = {'state': 'ready', 'session_id': 'owned-warm', 'prepared': {'stage_index': 0}}
    monkeypatch.setattr(saver, '_warm', lambda *args: {'re4': row})
    stops, removed = [], []
    monkeypatch.setattr(saver, '_warm_stop', lambda *args: stops.append(args))
    monkeypatch.setattr(mercmode, 'take_warm', lambda *args: removed.append(args))
    result = saver._resume_warm(worker, {'title': 're4'}, {}, now[0])
    assert result is None and len(stops) == 1 and stops[0][1] is row
    assert removed[0][1:] == (worker['name'], 're4')
    assert calls == []  # no resume, prepare, autoplay, or fallback mutation from this path
