import math
import pytest

from gbox.mercs.core import aim_book as A
from test_mercs_aim_book import prof, target

IDENTITY = ('round', 10, 2, 0, 4)


def request(core, enemy, now=0., identity=IDENTITY, *, bias=0., settled=True, clear=True):
    origin = (0., 140., 0.)
    plan = core.plan(enemy, origin, 'shotgun', now)
    yaw, pitch = A.angles(origin, plan.point)
    at = (1000*math.sin(yaw+bias)*math.cos(pitch), 140+1000*math.sin(pitch),
          1000*math.cos(yaw+bias)*math.cos(pitch))
    return core.shot(now, enemy, plan, origin=origin, at=at, los=True, family='shotgun',
        extra={'fire_identity': identity, 'aim_settled': settled, 'unconfounded': clear})


def core_at(tmp_path):
    return A.AimCore(prof(), {}, root=tmp_path, verified_only=True, log=False)


def test_unconfirmed_input_is_not_a_miss_or_a_lesson_even_if_target_hp_falls(tmp_path):
    core = core_at(tmp_path); enemy = dict(target(), generation=7)
    core.tick(0, [enemy]); shot = request(core, enemy)
    core.tick(.1, [dict(enemy, hp=enemy['hp']-10)])
    core.tick(.6, [enemy])
    assert shot['hits'] == 1 and shot['outcome'] == 'unconfirmed'
    assert core.stats['aimbook_unconfirmed'] == 1 and core.stats['aimbook_misses'] == 0
    assert not core.book.cells


@pytest.mark.parametrize('fault', ['weapon', 'round', 'generation', 'late', 'target_change'])
def test_discharge_cannot_confirm_another_weapon_round_allocation_or_target(tmp_path, fault):
    core = core_at(tmp_path); enemy = dict(target(), generation=7)
    request(core, enemy)
    identity = IDENTITY
    if fault == 'weapon': identity = (*IDENTITY[:-1], 7)
    if fault == 'round': identity = ('next', *IDENTITY[1:])
    if fault == 'generation': enemy = dict(enemy, generation=8)
    enemies = [enemy]
    if fault == 'target_change':
        other = dict(enemy, ptr=2)
        request(core, other, .05); enemies.append(other)
    assert not core.confirm_discharge(.4 if fault == 'late' else .1, identity, enemies, unconfounded=True)
    assert core.stats['aimbook_confirmed'] == 0


@pytest.mark.parametrize('fault', ['settling', 'explosive', 'wide_residual'])
def test_confirmed_discharge_with_unreliable_aim_does_not_calibrate(tmp_path, fault):
    core = core_at(tmp_path); enemy = dict(target(), generation=7)
    shot = request(core, enemy, bias=math.radians(30 if fault == 'wide_residual' else 3),
                   settled=fault != 'settling', clear=fault != 'explosive')
    assert core.confirm_discharge(.1, IDENTITY, [enemy], unconfounded=True)
    core.tick(.6, [enemy])
    assert shot['discharge_confirmed'] and not shot['learning_eligible']
    assert core.stats['aimbook_learned'] == 0 and not core.book.cells


def test_verified_directional_evidence_converges_and_legacy_offsets_stay_separate(tmp_path):
    legacy = A.AimBook(prof().title_id, tmp_path)
    key = legacy.key('shotgun', 'uEm10', '3-8m')
    legacy.cells[key] = dict(A.new_cell(), bias=[.17, .17], n=400)
    legacy.dirty = True; legacy.save(force=True)
    core = core_at(tmp_path); enemy = dict(target(z=700.), generation=7)
    assert core.book.correction('shotgun','uEm10','human','3-8m').yaw == 0
    errors = []
    for n in range(60):
        at = float(n)
        core.tick(at, [enemy])
        shot = request(core, enemy, at, bias=math.radians(3))
        errors.append(abs(shot['err'][0]))
        assert core.confirm_discharge(at+.1, IDENTITY, [enemy], unconfounded=True)
        if shot['contact']: enemy['hp'] -= 10
        core.tick(at+.2, [enemy]); core.tick(at+.6, [enemy])
    assert sum(errors[-10:]) < sum(errors[:10]) / 4
    assert core.stats['aimbook_learned'] == 60
    core.save()
    assert legacy.path != core.book.path and legacy.path.exists() and core.book.path.exists()
