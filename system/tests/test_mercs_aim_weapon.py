"""Weapon mastery uses matched native proof; synthetic tests do not certify live hits."""
import copy
import json
import math

import pytest

from gbox.mercs.core import aim_book as A
from test_mercs_aim_book import prof, target


def sample(**kw):
    return dict(outcome='hit', los=True, family='shotgun', cls='uEm10', kind='human', band='3-8m',
                weapon=0x16, pose='standing', discharge_confirmed=True, learning_eligible=True,
                resid=(.04, -.02), contact=True, uv=(0., .1), **kw)


def test_weapon_pose_and_title_cells_persist_without_overwriting_each_other(tmp_path):
    book = A.AimBook('re5', tmp_path, verified_only=True)
    first = sample()
    for _ in range(24):
        book.learn(first)
    key = book.wkey(0x16, 'shotgun', 'uEm10', 'standing', '3-8m')
    original = copy.deepcopy(book.weapons[key])
    for changes in ({'weapon': 0x17, 'resid': (-.04, .02)}, {'pose': 'downed', 'resid': (0., .04)}):
        for _ in range(24):
            book.learn(dict(first, **changes))
    assert book.weapons[key] == original
    assert len(book.weapons) == 3
    assert book.correction('shotgun', 'uEm10', 'human', '3-8m', weapon=0x16, pose='standing').yaw < 0
    assert book.correction('shotgun', 'uEm10', 'human', '3-8m', weapon=0x17, pose='standing').yaw > 0
    assert book.save(force=True)
    again = A.AimBook('re5', tmp_path, verified_only=True)
    assert again.weapons == book.weapons
    other = A.AimBook('re6', tmp_path, verified_only=True)
    assert not other.weapons and other.others  # only the family prior crosses titles
    assert not A.AimBook('re5', tmp_path).weapons  # verified and old unverified books stay separate


@pytest.mark.parametrize('field,value', [('discharge_confirmed', False), ('learning_eligible', False),
                                         ('outcome', 'unconfirmed'), ('los', False), ('weapon', None)])
def test_weapon_mastery_never_uses_unproved_or_ineligible_attempts_even_in_legacy_book(tmp_path, field, value):
    book = A.AimBook('legacy', tmp_path)
    book.learn(dict(sample(), **{field: value}))
    assert book.weapons == {}


def test_plan_optional_api_and_native_proof_flow_reach_weapon_log(tmp_path):
    core = A.AimCore(prof(), {}, root=tmp_path, verified_only=True)
    enemy = dict(target(), generation=7, motion=19)
    origin = (0., 140., 0.)
    legacy = core.plan(enemy, origin, 'shotgun', 0.)
    assert legacy.weapon is None and legacy.pose == 'motion:19'
    old_constructor = A.Plan(*legacy[:12])
    assert old_constructor.weapon is None and old_constructor.pose is None
    plan = core.plan(enemy, origin, 'shotgun', 0., weapon=22)
    assert plan.weapon == '0x0016' and plan._replace(point=plan.point).pose == 'motion:19'
    core.tick(0., [enemy])
    identity = ('round', 10, 1, 2, 22)
    shot = core.shot(0., enemy, plan, origin=origin, at=plan.point, los=True, family='shotgun',
                     extra={'fire_identity': identity, 'aim_settled': True, 'unconfounded': True})
    assert core.confirm_discharge(.1, identity, [enemy], unconfounded=True, source='native_post_emission_step')
    core.tick(.2, [dict(enemy, hp=enemy['hp']-10)])
    core.tick(.6, [enemy])
    assert shot['outcome'] == 'hit' and shot['learning_eligible']
    assert len(core.book.weapons) == 1
    core.save()
    row = json.loads(next((tmp_path / '_shots' / prof().title_id).glob('*.jsonl')).read_text().splitlines()[0])
    assert row['weapon'] == '0x0016' and row['pose'] == 'motion:19'
    assert row['discharge_source'] == 'native_post_emission_step'


@pytest.mark.parametrize('field,value', [
    ('bias', [math.nan, 0.]), ('bias', ['0.1', 0.]), ('bias', [True, 0.]), ('bias', [2., 0.]),
    ('pt', [0., math.inf]), ('pt', [0., -2.]), ('n', '3'), ('n', True), ('n', -1),
    ('hits', None), ('misses', .5), ('movers', math.nan), ('bias_probes', '1'),
    ('tol', math.nan), ('tol', 0.), ('lead_s', math.inf), ('updated', 'yesterday'), ('updated', 10**400),
    ('recent', None), ('recent', 'X'), ('res', [[.1]]), ('res', [[None, .1]]),
    ('res', [[.1, math.nan]]), ('log', ['bad']), ('log', [[1., 'hit', None]]),
])
def test_corrupt_cells_cannot_poison_loaded_weapon_family_or_universal_corrections(tmp_path, field, value):
    book = A.AimBook('re5', tmp_path, verified_only=True)
    bad = dict(A.new_cell(), **{field: value})
    wk = book.wkey(22, 'shotgun', 'uEm10', 'standing', '3-8m')
    book.path.parent.mkdir(parents=True)
    book.path.write_text(json.dumps({'cells': {'bad': bad}, 'weapons': {wk: bad}}))
    book.upath.parent.mkdir(parents=True)
    book.upath.write_text(json.dumps({'cells': {'bad': {'re6': bad}}}))
    loaded = A.AimBook('re5', tmp_path, verified_only=True)
    assert not loaded.cells and not loaded.weapons and not loaded.others
    assert all(math.isfinite(v) for v in loaded.correction('shotgun', 'uEm10', 'human', '3-8m', weapon=22)[:6])


def test_valid_partial_legacy_cells_remain_usable_and_weapon_storage_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'WEAPON_CELLS_MAX', 3)
    book = A.AimBook('re5', tmp_path)
    book.path.parent.mkdir(parents=True)
    weapons = {book.wkey(i, 'shotgun', 'uEm10', 'standing', '3-8m'):
               dict(A.new_cell(), updated=float(i)) for i in range(6)}
    weapons['not a partition'] = A.new_cell()
    book.path.write_text(json.dumps({'cells': {'shotgun|uEm10|3-8m': {'bias': [0., 0.], 'pt': [0., 0.]}},
                                     'weapons': weapons}))
    loaded = A.AimBook('re5', tmp_path)
    assert len(loaded.weapons) == 3 and sorted(v['updated'] for v in loaded.weapons.values()) == [3., 4., 5.]
    loaded.learn(sample())
    assert loaded.cells['shotgun|uEm10|3-8m']['n'] == 1


def test_corrupt_universal_partition_does_not_prevent_saving_new_verified_evidence(tmp_path):
    book = A.AimBook('re5', tmp_path, verified_only=True)
    book.upath.parent.mkdir(parents=True)
    key = book.ukey('shotgun', 'human', '3-8m')
    book.upath.write_text(json.dumps({'cells': {key: ['broken']}}))
    book.learn(sample())
    assert book.save(force=True)
    assert json.loads(book.upath.read_text())['cells'][key]['re5']['n'] == 1


def test_weapon_prior_has_at_most_four_actual_family_observations(tmp_path):
    book = A.AimBook('re5', tmp_path, verified_only=True)
    key = book.wkey(22, 'shotgun', 'uEm10', 'standing', '3-8m')
    book.weapons[key] = dict(A.new_cell(), n=10, bias=[.05, 0.])
    corr = lambda: book.correction('shotgun', 'uEm10', 'human', '3-8m', weapon=22, pose='standing')
    assert corr().n_prior == 0 and corr().yaw == -.05
    family = book.key('shotgun', 'uEm10', '3-8m')
    for n in (1, 2, 10, 400):
        book.cells[family] = dict(A.new_cell(), n=n, bias=[-.05, 0.])
        weight = min(n, 4)
        assert corr().n_prior == weight
        assert corr().yaw == pytest.approx((-10*.05+weight*.05)/(10+weight))


@pytest.mark.parametrize('game', ['re5', 're6'])
@pytest.mark.parametrize('change', ['weapon', 'pose', 'generation', 'unchanged'])
def test_title_shot_cache_rejects_another_weapon_pose_or_target_allocation(tmp_path, monkeypatch, game, change):
    from gbox.mercs.titles import re5_switch as R5, re6_switch as R6
    R = R5 if game == 're5' else R6
    monkeypatch.setattr(R, 'AIM_BOOK', True)
    enemy = dict(target(), generation=1, motion=2)
    player = {'ptr': 10, 'generation': 1, 'pos': (0., 0., 0.), 'weapon_id': 3, 'equipped': 0}
    origin = (0., 140., 0.)
    bot = R.Bot.__new__(R.Bot)
    bot.stats = {}
    core = A.AimCore(R.combat_profile(), bot.stats, root=tmp_path, verified_only=True, log=False)
    bot._aim_core = lambda: core
    bot._item = 0x16
    bot._aim_family = lambda: 'shotgun'
    family = bot._aim_family() if game == 're5' else R.aim_family(player)
    weapon = bot._item if game == 're5' else player['weapon_id']
    old = core.plan(enemy, origin, family, 0., weapon=weapon)
    bot._ab_plan = (A.AimCore.target_key(enemy), old)
    if change == 'weapon':
        bot._item, player['weapon_id'] = 0x17, 4
    elif change == 'pose':
        enemy = dict(enemy, motion=7)
    elif change == 'generation':
        enemy = dict(enemy, generation=2)
    used = []
    original = core.shot
    def capture(now, target, plan, **kw):
        used.append(plan)
        return original(now, target, plan, **kw)
    core.shot = capture
    snap = {'player': player, 'enemies': [enemy], 'throwables': []}
    if game == 're5':
        bot._ab_snap = snap
        monkeypatch.setattr(R, 'AIM_BOOK_GATE', True)
        contact = bot._aim_book_contact(enemy, origin, old.point)
        assert (contact is None) == (change != 'unchanged')
        bot._aim_book_shot({'target': enemy['ptr'], 'origin': origin, 'dot': old.point}, .2)
    else:
        bot._snap = snap
        bot.aim_since = 0.
        bot.is_blocked = lambda *args: False
        bot._aim_learning_clear = lambda *args: True
        bot._aim_book_shot(player, enemy, origin, old.point, 'laser', True, .2)
    assert not bot.stats.get('aimbook_error')
    assert len(used) == 1 and (used[0] is old) == (change == 'unchanged')
    assert core.ledger.open[-1]['weapon'] == A.weapon_key(bot._item if game == 're5' else player['weapon_id'])
    assert core.ledger.open[-1]['pose'] == A.target_pose(enemy)
    assert core.ledger.open[-1]['target'] == A.AimCore.target_key(enemy)
