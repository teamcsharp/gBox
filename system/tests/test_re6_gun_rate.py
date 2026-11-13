"""General gun rate must reach the native animation as well as its interval."""
import json
import struct
from pathlib import Path

import pytest

from gbox.mercs.titles import re6_switch as R, re6_switch_mods as M
from test_re6_switch import Adapter, round_guest, weapon_table


@pytest.fixture(autouse=True)
def clean_state():
    M.ORIG.clear()
    yield
    M.ORIG.clear()


def armed(weapon=4):
    guest = round_guest()
    weapon_table(guest)
    ad = Adapter(guest)
    p = R.snapshot(guest)['player']['ptr']
    guest.put(p+R.P_SLOTS+8, bytes([1, 0])+struct.pack('<H', 0x100+weapon))
    guest.i32(p+R.P_EQUIPPED, 0)
    guest.f32(p+M.UNIT_DELTA, 1.)
    guest.q(p+M.UNIT_ACTION, guest.obj('cPlAction_pl_act_weapon_fire', 0x100))
    M.run(ad, 'fire_rate', multiplier=20, magnum=20)
    return guest, ad, p


@pytest.mark.parametrize('weapon', sorted(M.GUN_IDS))
def test_each_known_gun_uses_fast_fire_action_then_restores_normal_walk(weapon):
    g, ad, p = armed(weapon)
    out = M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    assert out['verified']
    assert struct.unpack('<f', g.rd(p+M.UNIT_DELTA, 4))[0] == 20.
    assert M.ORIG[id(ad)]['gun_animation_last']['weapon'] == weapon
    g.q(p+M.UNIT_ACTION, g.obj('cPlAction_pl_act_walk', 0x100))
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    assert struct.unpack('<f', g.rd(p+M.UNIT_DELTA, 4))[0] == 1.


def test_real_cap_and_profile_are_twenty_not_fixture_overrides():
    g, ad, p = armed()
    assert M.FIRE_MAX == 20.
    assert M.run(ad, 'fire_rate', multiplier=80, magnum=20)['fire_rate_x'] == 20.
    for i in M.GUN_IDS:
        expected = M.FIRE_ORIGINAL[i]/(M.SNIPER_FIRE_X if i in M.SNIPER_RECORDS else 20.)
        assert M.fire_interval(i, 20., magnum=20.) == pytest.approx(max(M.FIRE_FLOOR, expected))
    profile = json.loads((Path(__file__).parents[1]/'profiles/gamedata/01002A000CD48000-ram.json').read_text())
    assert dict(profile['mercs']['playing_ops'])['fire_rate'] == {'multiplier':20, 'magnum':20, 'throw':10}


@pytest.mark.parametrize('action', ['cPlAction_pl_act_walk', 'cPlAction_pl_act_wait',
    'cPlAction_pl_act_item_heal', 'cPlAction_pl_act_damage', 'unknown'])
def test_ordinary_gun_does_not_speed_other_actions(action):
    g, ad, p = armed()
    g.q(p+M.UNIT_ACTION, g.obj(action, 0x100))
    ad.writes.clear()
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    assert not any(address == p+M.UNIT_DELTA for address, data in ad.writes)


@pytest.mark.parametrize('bad', ['weapon', 'generation', 'foreign_rate', 'action_race'])
def test_stale_or_foreign_facts_cannot_apply_a_gun_speed(bad):
    g, ad, p = armed()
    snap = R.snapshot(g)
    if bad == 'weapon': snap['player']['weapon_id'] = 5
    elif bad == 'generation': snap['player']['generation'] += 1
    elif bad == 'foreign_rate': g.f32(p+M.UNIT_DELTA, .5)
    else:
        old = ad.read_memory
        reads = [0]
        def changing(at, size):
            if at == p+M.UNIT_ACTION:
                reads[0] += 1
                if reads[0] == 2:
                    g.q(at, g.obj('cPlAction_pl_act_walk', 0x100))
            return old(at, size)
        ad.read_memory = changing
    ad.writes.clear()
    M.maintain(ad, snap, clock=lambda: 10.)
    assert not any(address == p+M.UNIT_DELTA for address, data in ad.writes)
    assert not M.ORIG[id(ad)].get('gun_animation_last')


def test_disable_or_change_rate_restores_the_previous_owned_multiplier():
    g, ad, p = armed()
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    M.run(ad, 'fire_rate', multiplier=4)
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    assert struct.unpack('<f', g.rd(p+M.UNIT_DELTA, 4))[0] == 4.
    M.run(ad, 'fire_rate', on=False)
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.)
    assert struct.unpack('<f', g.rd(p+M.UNIT_DELTA, 4))[0] == 1.
