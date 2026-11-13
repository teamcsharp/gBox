"""Retired mine identities stop constraining routes without inventing a blast."""
import pytest

from gbox.mercs.titles import re5_native_mine_tactic as N, re5_switch_mines as M
from gbox.mercs.titles import re5_movement_safety as S
from test_re5_native_mine_tactic import (
    BASE, PLAYER, UNIT, scene, stats, memory, receipt, mine_memory, verified_test_backend,
)


@pytest.mark.parametrize('field', ['generation', 'vtable', 'owner'])
def test_native_identity_retirement_is_double_read_and_survives_prompt_only_ticks(field):
    mem, snap = mine_memory()
    assert N.ground(mem, BASE, snap['player'])
    if field == 'generation': mem.q(UNIT+0x1A00, 43)
    elif field == 'vtable': mem.q(UNIT, BASE+0x2000)
    else: mem.q(UNIT+0x1A10, PLAYER+0x1000)
    assert N.ground(mem, BASE, snap['player']) == []
    witness = N.ground_observations(mem, snap['player'])[0]
    assert witness['ptr'] == UNIT and witness['generation'] == 42
    assert witness['native_owner'] == PLAYER and witness['retired_observed'] is True
    assert 'identity changed' in witness['retirement_reason']
    assert not getattr(mem, N.GUARD_ATTRIBUTE)['actors']
    assert N.ground(mem, BASE, snap['player']) == []
    assert N.ground_observations(mem, snap['player']) == [witness]


def test_changing_allocation_or_unreadable_memory_is_not_retirement():
    mem, snap = mine_memory()
    assert N.ground(mem, BASE, snap['player'])
    old = mem.rd
    calls = [0]
    def racing(at, count):
        if at == UNIT+0x1A00:
            calls[0] += 1
            mem.q(at, 43+calls[0])
        return old(at, count)
    mem.rd = racing
    assert N.ground(mem, BASE, snap['player']) is None
    guard = getattr(mem, N.GUARD_ATTRIBUTE)
    assert guard['actors'] == {UNIT: 42} and not guard.get('retirements')
    assert N.ground_observations(mem, snap['player']) is None


@pytest.mark.parametrize('offset', [0x27B9, 0x28C1, 'primary', 'proximity'])
@pytest.mark.parametrize('scan', [False, True])
def test_short_flag_read_is_unknown_never_inactive_retirement(offset, scan):
    mem, snap = mine_memory()
    mem.q(UNIT+0x2710, UNIT+0x5000)
    mem.q(UNIT+0x28C8, UNIT+0x6000)
    assert N.ground(mem, BASE, snap['player'])
    guard = getattr(mem, N.GUARD_ATTRIBUTE)
    guard['needs_scan'] = scan
    if isinstance(offset, str):
        address = UNIT+(0x5000 if offset == 'primary' else 0x6000)+0x14
    else:
        address = UNIT+offset
    old = mem.rd
    mem.rd = lambda at, count: b'' if at == address and count == 1 else old(at, count)
    assert N.ground(mem, BASE, snap['player']) is None
    assert N.ground_observations(mem, snap['player']) is None
    assert guard['actors'] == {UNIT: 42}


def placed():
    s, st, mem = scene(), stats(), memory()
    mines = M.Mines(st); mines.new_round(0.)
    mines.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('observation must not allocate'))
    st['native_mine_force_receipts'] = [
        {'id': 'original', 'owner': list(N.identity(s, st)), 'receipt': receipt()}]
    mines.observe_native(mem, s, 1.)
    return mines, s, st


@pytest.mark.parametrize('proof', ['identity', 'inactive', 'trigger'])
def test_owned_positive_witness_retires_escape_site_even_after_absence_removed_live_book(proof):
    mines, s, st = placed()
    missing = dict(s, ground_mines=[], ground_mine_observations=[])
    mines.watch(s['player'], missing, 2.)
    assert not mines.bombs and UNIT in mines._native_escape['sites']
    witness = dict(ptr=UNIT, generation=42, native_owner=PLAYER)
    if proof == 'identity': witness['retired_observed'] = True
    elif proof == 'inactive': witness['active'] = False
    else: witness['trigger_observed'] = True
    fresh = dict(s, ground_mines=[], ground_mine_observations=[witness])
    mines.watch(s['player'], fresh, 3.)
    mines.watch(s['player'], fresh, 3.1)
    assert UNIT not in mines._native_escape['sites']
    assert not mines.native_sites(fresh)
    assert st['native_mine_retirements_verified'] == 1
    assert st['mine_blasts'] == st['mine_kills'] == st['mine_blast_hp_loss'] == 0
    assert st['native_mine_removals_unattributed'] == 1  # cause was not captured at disappearance


@pytest.mark.parametrize('bad', ['generation', 'owner', 'unknown', 'stale_census', 'incomplete'])
def test_uncertain_or_foreign_witness_cannot_retire_a_retained_hazard(bad):
    mines, s, st = placed()
    row = dict(ptr=UNIT, generation=42, native_owner=PLAYER, retired_observed=True)
    if bad == 'generation': row['generation'] = 41
    elif bad == 'owner': row['native_owner'] = PLAYER+1
    elif bad == 'unknown': row.pop('retired_observed')
    fresh = dict(s, ground_mines=[], ground_mine_observations=[row])
    if bad == 'stale_census': fresh['ground_mines'] = s['ground_mines']
    elif bad == 'incomplete': fresh['ground_mines'] = None
    mines.watch(s['player'], fresh, 2.)
    assert UNIT in mines._native_escape['sites']
    assert st.get('native_mine_retirements_verified', 0) == 0


def test_old_witness_never_removes_reused_pointer_new_mine_generation():
    mines, s, st = placed()
    result = receipt()
    result['mines'][0]['generation'] = 43
    mines._merge_native({'id': 'new-generation', 'owner': N.identity(s, st),
                         'receipt': result, 'archive': None}, 2., census=[])
    fresh = dict(s, ground_mines=[dict(ptr=UNIT, generation=43, pos=(0., 0., 0.))],
                 ground_mine_observations=[dict(ptr=UNIT, generation=42, native_owner=PLAYER, retired_observed=True)])
    mines.watch(s['player'], fresh, 3.)
    assert UNIT in mines.bombs and UNIT in mines._native_escape['sites']
    assert mines._native_generations[UNIT] == 43


def test_old_generation_trigger_and_empty_census_do_not_remove_new_escape_site():
    mines, s, st = placed()
    result = receipt()
    result['mines'][0]['generation'] = 43
    mines._merge_native({'id': 'new-generation', 'owner': N.identity(s, st),
                         'receipt': result, 'archive': None}, 2., census=[])
    fresh = dict(s, ground_mines=[], ground_mine_observations=[
        dict(ptr=UNIT, generation=42, native_owner=PLAYER, trigger_observed=True)])
    mines.watch(s['player'], fresh, 3.)
    assert not mines.bombs  # absence can remove the live book, not the escape hazard
    assert UNIT in mines._native_escape['sites'] and mines._native_generations[UNIT] == 43
    assert st['native_mine_triggers_observed'] == 0
    assert st['native_mine_removals_unattributed'] == 1


def test_village_retained_old_site_stops_vetoing_east_only_after_positive_retirement():
    from types import SimpleNamespace
    mines, s, st = placed()
    start = (-7507., 100., 5942.)
    old = (-7078.5156, 0., 6470.1147)
    east = (-7307., 100., 5942.)
    mines.bombs[UNIT] = old
    mines._native_escape.update(center=start, sites={UNIT: old, 715: (-7619.44, 100., 6011.70),
                                                    716: (-7619.44, 100., 5832.54)}, pending=False)
    s['player']['pos'] = start
    bot = SimpleNamespace(mines=mines)
    absent = dict(s, ground_mines=[], ground_mine_observations=[])
    mines.watch(s['player'], absent, 2.)
    assert not S._mine_clear(bot, absent, start, east)
    proof = dict(s, ground_mines=[], ground_mine_observations=[
        dict(ptr=UNIT, generation=42, native_owner=PLAYER, retired_observed=True)])
    mines.watch(s['player'], proof, 3.)
    assert S._mine_clear(bot, proof, start, east)
    assert len(mines.native_sites(proof)) == 2  # current armed mines retain their exclusions
