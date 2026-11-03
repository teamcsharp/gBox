"""Cluster fc64fa11608d5358 (RE5 Mercenaries, 2026-10-29): 'grabbed from the front' - 196 loss in 0.2 s,
position and heading identical across 6 ticks, ldown+rright held (a grab or hold), and the nearest Majini standing on
top of him.

The cause the data points to: with the gun down while a Majini stood inside arm's length - the 2026-10-28 damage
clusters show 29 of 31 hits within 1.5 m while the gun was on another target or coming down - pick() had no tier that
fought a Majini at arm's length regardless of which one the laser was on. The gun-down swing (and the trigger on the
dotted one, 3-5 m out) left him inside the grab. This batch adds one tier: a Majini at arm's length in front comes
before everything else, dot included - the same tier's geometry, at the same contact radius, with the same hysteresis
(FRONT_CONE), so the swing never drops the gun while one is inside CONTACT_R in front.
"""
import json
import math
from pathlib import Path

from gbox.mercs.titles import re5_combat as C, re5_engage as E
from tests.test_re5_combat import ENEMY, snap, world
from tests.test_re5_engage import at
import tests.test_re5_engage as ENG

P = {**ENG.P, "rot": math.radians(48.5)}   # rot 0.8472421132863364 rad, the fixture's heading


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures' / 'mercs_incidents' /
                       're5_switch_hold_in_crowd.json').read_text())


def test_the_fixture_replays_and_is_the_cluster():
    from gbox.mercs import damage_clusters as D
    fx = fixture()
    assert fx['schema'] == 'gbox.mercs.incident-replay/1'
    assert fx['cluster']['signature'] == 'grabbed_front'
    assert fx['held'] == ['ldown', 'rright'] and fx['loss'] == 196
    assert fx['hp_before'] == 1000 and fx['hp_after'] == 804
    assert all(t['held'] == ['ldown', 'rright'] and t['pos'] == fx['snapshot']['player']['pos']
               for t in fx['preceding_history'])
    ev = {k: fx[k] for k in ('title', 'snapshot', 'held', 'hp_before', 'hp_after', 'hp_max', 'loss', 'observed_at',
                             'preceding_history')}
    assert D.classify(D.features(dict(ev, logic=fx['counters']), fx['cluster']['game_id']))[0] == \
        fx['cluster']['signature']


def test_at_arms_length_in_front_is_fought_before_the_one_under_the_dot_and_any_further_target():
    # the hit moment: a Majini 0 cm away in front (slot 22, the one on top of him), the dot on a target elsewhere,
    # and 13 more standing within 2.4 m - the old pick() could swing at the dotted one with the gun down while this
    # one was inside the grab
    contact = at(0.0, 10.0, 22)                                  # the one at arm's length in front
    dotted = at(20.0, 400.0, 1)                                  # the one under the laser dot
    others = [at(deg, 900.0, s) for s, deg in ((3, -30), (4, 30), (5, -60), (6, 60), (7, 150), (8, 200))]
    target, why = E.pick(P, others + [dotted, contact], dotted=dotted, held=1)
    assert target is contact and "arm's length" in why


def test_a_close_one_behind_him_still_turns_to_first():
    # the tier's front cone: the Majini at arm's length but behind his heading is a turn-to, not the fight target
    behind = at(150.0, 40.0, 3)
    far = at(10.0, 600.0, 1)
    target, why = E.pick(P, [far, behind], held=1)
    assert target is behind and "turn to him" in why


def test_the_fixture_snapshot_never_lets_the_gun_down_while_the_near_one_is_in_front():
    fx = fixture()
    p = fx['snapshot']['player']
    enemies = [e for e in fx['snapshot']['enemies'] if e['hp'] > 0]
    # a Majini is on top of him in the fixture: 0 m away, inside CONTACT_R, inside the front cone (the same geometry
    # the swing gate and pick()'s contact-front tier use)
    on_top = next(e for e in enemies if e['slot'] == 22)
    assert E.flat(p['pos'], on_top['pos']) <= E.CONTACT_R
    # the swing gate in re5_combat: a gun-down turn away from the held target happens only when front_threat is None
    assert E.front_threat(p, enemies, exclude=on_top['ptr']) is not None
    # ... and the held target loses to the contact-front tier (pick() re-runs with him in the pool)
    target, _ = E.pick(p, enemies, held=on_top['ptr'], dotted=on_top)
    assert target is not None and E.flat(p['pos'], target['pos']) <= E.CONTACT_R


def test_the_combat_layer_keeps_the_gun_up_against_the_fixture_snapshots(tmp_path):
    fx = fixture()
    m = world()
    bot = C.Combat(m, {}, clock=lambda: 0.0, learn_dir=tmp_path, lessons=lambda e: None)
    s = snap(m, enemy=fx['snapshot']['enemies'][0]['pos'], hp=fx['snapshot']['enemies'][0]['hp'])
    s['enemies'] = [dict(e, slot=e['slot'], ptr=e['ptr']) for e in fx['snapshot']['enemies']]
    s['player'].update(pos=tuple(fx['snapshot']['player']['pos']), rot=fx['snapshot']['player']['rot'])
    s['laser'] = None                                            # the gun is down: no ray on the snapshot's tick
    keys = bot.tick(s, s['player'], s['enemies'][0], 1.0)['hold']
    assert 'l1' in keys                                          # gun up: the front tier fights the near one
    assert 'swinging' not in bot.stats['combat']                 # no gun-down swing while a Majini is inside CONTACT_R
