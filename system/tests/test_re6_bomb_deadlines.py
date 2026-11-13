import threading
import types
import math

import pytest

from gbox.mercs import re6_bomb_deadlines as D, remote_mines as M, re6_remote_control as C
from gbox.mercs.re6_remote_control import RingFlight
from gbox.mercs.titles import re6_switch_native as N

TITLE = '01002A000CD48000'


def snap(at=0, units=(), *, generation=1):
    return {'player': {'ptr': 0x200000000, 'generation': generation, 'pos': [0, 0, at], 'hp': 900},
            'throwables': list(units), 'enemies': []}


def bomb(unit=10, generation=1, at=0, action=D.SETTING):
    return {'unit': unit, 'generation': generation, 'kind': 'remote', 'pos': [0, 0, at], 'action': action}


def stats(**extra):
    return dict(round_evidence_id='round-1', screen='playing', **extra)


@pytest.fixture(autouse=True)
def clear_receipts(monkeypatch, tmp_path):
    monkeypatch.setattr(C, 'ROOT', tmp_path)
    D._PLACED.clear()
    yield
    D._PLACED.clear()


def test_placement_time_is_native_confirmation_not_ring_request_or_later_read():
    D.record_placement(0x200000000, 1, {'unit': 10, 'generation': 1, 'placed_at': 103})
    book, st = D.Deadlines(), stats(mine_ring_requested_at=100)
    book.observe(snap(units=[bomb()]), st, 104)
    assert st['mine_deadline_at'] == 108 and st['mine_elapsed_s'] == 1
    assert st['mine_timing_source'] == 'native_placed_armed'
    book.observe(snap(units=[bomb(), bomb(11)]), st, 106)
    assert st['mine_deadline_at'] == 108


def test_hand_thrown_bomb_reports_first_observed_placed_timing_honestly():
    book, st = D.Deadlines(), stats()
    assert not book.observe(snap(units=[bomb(action='cWpAction_wp_act_throw')]), st, 100)
    book.observe(snap(units=[bomb()]), st, 101)
    assert st['mine_deadline_at'] == 106
    assert st['mine_timing_source'] == 'first_observed_placed'


def test_missed_deadline_is_once_per_allocation_and_preserves_failure_context():
    book, st = D.Deadlines(), stats(mine_detonate_reason='player held; flag withheld')
    book.observe(snap(units=[bomb()]), st, 100)
    for at in (105.1, 106, 108):
        book.observe(snap(units=[bomb()]), st, at)
    assert st['mine_deadline_misses'] == 1
    row, = st['mine_deadline_incidents']
    assert row['placed_at'] == 100 and row['deadline_at'] == 105
    assert row['reason'] == 'player held; flag withheld' and row['player_pos'] == [0, 0, 0]
    book.observe(snap(units=[bomb(generation=2)]), st, 110)
    assert st['mine_deadline_at'] == 115


def test_unknown_census_does_not_reset_fuse_but_complete_empty_does():
    book, st = D.Deadlines(), stats()
    book.observe(snap(units=[bomb()]), st, 100)
    unreadable = snap()
    unreadable['throwables'] = None
    book.observe(unreadable, st, 104)
    assert st['mine_deadline_at'] == 105
    book.observe(snap(), st, 104.5)
    assert st['mine_deadline_pending'] == 0 and not st['mine_escape_required']


def test_native_flag_and_observed_blast_have_distinct_receipts():
    book, st = D.Deadlines(), stats()
    book.observe(snap(units=[bomb()]), st, 100)
    book.triggered({'verified': True, 'detonated': [10], 'triggered_at': 104}, st, 104)
    assert st['mine_deadline_last']['blast_confirmed'] is False
    book.observe(snap(units=[bomb(action=D.BLAST)]), st, 104.3)
    assert st['mine_deadline_last']['blast_confirmed'] is True
    assert st['mine_deadline_last']['elapsed_s'] == 4.3
    assert st['mine_blasts_observed'] == 1
    book.observe(snap(units=[bomb(action=D.BLAST)]), st, 105)
    assert st['mine_blasts_observed'] == 1


def test_disappearance_after_flag_is_not_claimed_as_observed_explosion():
    book, st = D.Deadlines(), stats()
    book.observe(snap(units=[bomb()]), st, 100)
    book.triggered({'verified': True, 'detonated': [10]}, st, 102)
    book.observe(snap(), st, 103)
    assert st['mine_deadline_last']['outcome'] == 'unit_disappeared_after_flag'
    assert st['mine_deadline_last']['blast_confirmed'] is False


def test_blast_first_observed_after_deadline_records_late_observation():
    book, st = D.Deadlines(), stats()
    book.observe(snap(units=[bomb()]), st, 100)
    book.observe(snap(units=[bomb(action=D.BLAST)]), st, 106)
    assert st['mine_deadline_misses'] == 1
    assert st['mine_deadline_last']['observed_within_five_seconds'] is False


def test_bomb_or_grenade_phase_cannot_starve_existing_bomb_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: calls.append(1) or
                        {'verified': True, 'count': 1, 'detonated': [10]})
    step = M.control(None, {'map_id': TITLE}, lambda: types.SimpleNamespace(bomb_phase='wait', nade={'phase': 'aim'}))
    st = stats()
    step.observe(snap(units=[bomb()]), st, 100)
    assert not calls and st['mine_escape_required']
    step.observe(snap(1200, [bomb()]), st, 104)
    assert calls == [1] and st['mine_flag_detonations'] == 1
    step.observe(snap(1200, [bomb()]), st, 104.2)
    assert calls == [1]  # no repeated flag writes while its blast is pending


def test_overdue_bomb_never_bypasses_clearance_and_disabled_drops_still_service_it(monkeypatch):
    calls = []
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: calls.append(1) or
                        {'verified': True, 'count': 1, 'detonated': [10]})
    step = M.control(None, {'map_id': TITLE})
    st = stats(remote_mines={'enabled': False, 'detonate_after_s': 300})
    step.observe(snap(units=[bomb()]), st, 100)
    step.observe(snap(units=[bomb()]), st, 106)
    assert not calls and st['mine_deadline_misses'] == 1
    step.observe(snap(1200, [bomb()]), st, 106.2)
    assert calls == [1]
    assert M.policy(st)['detonate_after_s'] == 5


def test_tuned_native_clearance_keeps_escape_active_until_flag_gate_can_pass(monkeypatch):
    calls = []
    monkeypatch.setattr(N.R, 'BOMB_MARGIN_CM', 300.)
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: calls.append(1) or
                        {'verified': False, 'reason': 'player is held'})
    step, st = M.control(None, {'map_id': TITLE}), stats()
    step.observe(snap(1150, [bomb()]), st, 100.)
    assert st['mine_required_clearance_cm'] == 1200.
    assert st['mine_escape_required'] and not calls
    step.observe(snap(1200, [bomb()]), st, 100.2)
    assert calls == [1] and st['mine_deadline_pending'] == 1
    assert st['mine_detonate_last_failure'] == 'player is held'
    assert not st['mine_detonate_last']['verified']


def test_ring_worker_never_releases_movement_or_waits_for_native_allocation(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def ring(*a, **kw):
        entered.set()
        assert release.wait(2)
        return {'state': 'confirmed', 'placed': 1, 'units': []}
    monkeypatch.setattr(C, 'emergency_ring_now', ring)
    step = M.control(None, {'map_id': TITLE})
    st = stats(ring_flash_at=100.)
    try:
        out = step(snap(), st, 100, lambda _: pytest.fail('native ring must preserve pad input'))
        assert out['pending'] and not out['fired'] and entered.wait(1)
        assert step(snap(), st, 101)['fired'] is False
        assert st['mine_ring_requests'] == 1
    finally:
        release.set()
        step.close()


def test_late_ring_receipt_cannot_attach_to_a_new_round():
    f = RingFlight()
    entered, release = threading.Event(), threading.Event()
    owner = ('r1', 1, 2)
    def work(cancelled):
        entered.set()
        assert release.wait(2)
        assert cancelled()
        return {'placed': 5}
    try:
        assert f.submit(owner, work) and entered.wait(1)
        assert f.poll(('r2', 1, 2)) is None
        release.set()
        f.thread.join(1)
        assert f.poll(('r2', 1, 2)) is None
    finally:
        release.set()
        f.close()


def test_deadline_escape_moves_even_with_a_loaded_gun_and_enemy_in_exit_direction():
    from tests.test_re6_fire_commitment import crowd
    bot, s = crowd()
    bot.stats['mine_escape_required'] = True
    bot._open_heading = lambda *a, **kw: 0
    p = s['player']
    p.update(equipped=0, ammo=10)
    out = bot._bomb_walk(p, (0, -200), 0, 200, 0, 100, act='bomb_escape', live=s['enemies'])
    assert 'lup' in out['hold']
    assert 'zr' not in out['hold']
    assert bot.stats['bomb_kicks'] == 0
    assert not bot.stats.get('escape_fights')
    # The doctrine must not replace this deadline route with another item or
    # stationary fighting operation after the primary decision returns.
    assert bot._respond(s, out, 100) == out


def test_rooftop_deadline_escape_retains_final_movement_with_close_enemies():
    """The observed 202..949cm escape must not continually restart kicks."""
    from tests.test_re6_fire_commitment import crowd
    from tests.test_re6_movement_safety import square, end
    from gbox.mercs.titles import re6_movement_safety as S
    bot, s = crowd()
    bot.stats.update(mine_escape_required=True, mine_avoid_positions=[[5000., 0., 5000.]])
    s.update(navmesh=square(10000.), throwables=[dict(bomb(), pos=[5000., 0., 5000.])])
    s['player'].update(equipped=0, ammo=10, state=0, action='cPlAction_pl_act_walk',
                       bomb={'out': True, 'armed': True})
    bot.push = {'h': math.pi, 'until': 200.}  # an old crowd push toward the new bomb
    for now, clearance in ((100., 202.), (101.2, 303.), (102.9, 315.), (104.1, 366.), (115.8, 949.)):
        bot.clock = lambda: now
        s['player']['pos'] = (5000., 0., 5000. + clearance)
        for i, e in enumerate(s['enemies']):
            e['pos'] = (5000. + i * 30., 0., 5100. + clearance)
        out = bot.tick(s)
        assert set(out['hold']) & S.LEFT
        assert not {'zl', 'zr'} & set(out['hold'])
        assert S._bomb_clear(bot, s, s['player']['pos'], end(s, out['hold']))
        assert bot._movement_guard['previous'][3] == out['hold']
        receipt = bot.stats['bomb_escape_output']
        assert receipt['final_hold'] == list(out['hold'])
        assert receipt['measurement'] == 'brain_final_before_engine_transport'
    assert bot.stats['bomb_kicks'] == 0
    assert bot.stats.get('escape_fights', 0) == 0


def test_bomb_side_recovery_never_presses_opposite_lateral_directions():
    from tests.test_re6_fire_commitment import crowd
    from gbox.mercs.titles.re6_switch_wall import stick_heading
    bot, s = crowd()
    bot.stats['mine_escape_required'] = True
    bot.bomb_side_until, bot.detour = 101., 'lleft'
    bot._open_heading = lambda *a, **kw: -3 * math.pi / 4
    out = bot._bomb_walk(s['player'], (0, 200), 0, 200, 0, 100, act='bomb_escape', live=s['enemies'])
    assert set(out['hold']) == {'ldown', 'lleft'}
    assert stick_heading(out['hold'], 0.) is not None


def test_ring_escape_anchor_does_not_flip_when_nearest_bomb_changes():
    from tests.test_re6_fire_commitment import crowd
    bot, s = crowd()
    p = s['player']
    p.update(equipped=0, bomb={'out': True, 'armed': True})
    s['throwables'] = [bomb(10, at=-200), bomb(11, at=200)]
    bot.stats.update(mine_escape_required=True, mine_avoid_positions=[[0, 0, -200], [0, 0, 200]])
    anchors = []
    bot._bomb_walk = lambda p, anchor, *args, **kw: anchors.append(anchor) or {'hold': ('ldown',)}
    for z in (-20, 20):
        p['pos'] = (0, 0, z)
        assert bot._bomb_escape(p, s, 100)['hold'] == ('ldown',)
    assert anchors == [(0, 0), (0, 0)]


def test_timed_out_deadline_escape_returns_the_gun_to_the_fight_and_keeps_the_route():
    """A timed escape that cannot clear must not walk the round away with the gun down.

    Live 2026-11-13 (RE6 No Mercy, round 33cba3ca): the combo went 24 -> 0 while the bot was 'out first' inside a
    1100 cm bomb clearance it could not reach, with six zombies within 4.6 m and the gun never firing again. After
    ESCAPE_TIMEOUT_S the pure-movement monopoly ends: the retreat route is kept and the aim/fire gates run. The
    blast is never waived - it is still set off only from the rule's clearance, and the missed deadline remains in
    mine_deadline_incidents.
    """
    from tests.test_re6_fire_commitment import crowd
    bot, s = crowd()
    p = s['player']
    p.update(equipped=0, ammo=10)
    bot._open_heading = lambda *a, **kw: 0
    # Enemies 4 m to the side: outside ESCAPE_FIGHT_R, inside ESCAPE_TIMEOUT_FIGHT_R.
    s['enemies'][0]['pos'] = (400., 0., 0.)
    s['enemies'][1]['pos'] = (450., 0., 20.)
    bot.stats.update(mine_escape_required=True, mine_oldest_placed_at=100., mine_elapsed_s=13.)
    out = bot._bomb_walk(p, (0, -200), 0, 500, 0, 113., act='bomb_escape', live=s['enemies'])
    assert out is None                                          # the normal combat tick runs, not a gun-down walk
    assert bot.stats['escape_timeouts'] == 1
    assert bot._combat_escape_move                              # the retreat direction is kept for _escape_fire_inputs
    # Still inside the five-second deadline: pure movement, no aim, no trigger.
    bot.stats.update(mine_elapsed_s=1.)
    out = bot._bomb_walk(p, (0, -200), 0, 200, 0, 101., act='bomb_escape', live=s['enemies'])
    assert out is not None and not ({'zl', 'zr'} & set(out['hold']))
    # One timeout per bomb set, not one per tick.
    bot.stats.update(mine_elapsed_s=20.)
    bot._bomb_walk(p, (0, -200), 0, 200, 0, 120., act='bomb_escape', live=s['enemies'])
    assert bot.stats['escape_timeouts'] == 1


def test_engine_services_deadlines_before_prompt_only_ticks(monkeypatch, tmp_path):
    from gbox.mercs import engine, lessons, grenade_ring
    monkeypatch.setattr(lessons, 'ROOT', tmp_path / 'mercs' / 'lessons')
    events, index, st = [], [-1], {}
    memory = types.SimpleNamespace(adapter=object())
    class Brain:
        def prompt_ok(self, *a): return True
        def tick(self, s): pytest.fail('QTE owns controller input')
        def save(self): pass
    class Driver:
        frame = None
        def snapshot(self, m): return snap(units=[bomb()])
        def screen(self, m, s): return 'playing'
        def progress(self, s): return {'timer': 60., 'kills': 1, 'score': 100}
        def prompt_source(self, *a): return lambda: None
        def prompt_keys(self, key): return [('y',)]
    class Prompts:
        mashing = True
        def __init__(self, *a, **kw): pass
        def step(self, now, **kw):
            events.append('prompt')
            return [('y',)]
    def remote(*a): pytest.fail('ordinary ring work is bypassed by QTE')
    remote.observe = lambda *a: events.append('deadline')
    remote.close = lambda: events.append('closed')
    monkeypatch.setattr(M, 'control', lambda *a, **kw: remote)
    monkeypatch.setattr(grenade_ring, 'control', lambda *a, **kw: None)
    monkeypatch.setattr(engine, 'PromptPresser', Prompts)
    def stopped():
        index[0] += 1
        return index[0] >= 2
    engine.play_round({'map_id': TITLE}, memory, lambda rows: None, stopped, st,
                      brain=Brain(), driver=Driver(), clock=lambda: index[0] * .2, sleep=lambda _: None)
    assert events == ['deadline', 'prompt', 'deadline', 'prompt', 'closed']
