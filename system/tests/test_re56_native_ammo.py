"""Ammo interventions use the real title mods with guarded session ownership."""
import struct
import threading

import pytest

from gbox.mercs.titles import re5_switch_native as N5, re6_switch_native as N6
from gbox.mercs.titles import re5_switch_mods as M5, re6_switch_mods as M6
from tests.test_re5_switch_mods import weapon_guest, Adapter as A5, flag
from tests.test_re6_switch import round_guest, Adapter as A6


@pytest.fixture(params=[5, 6])
def ammo(request):
    number = request.param
    mods, native = (M5, N5) if number == 5 else (M6, N6)
    mods.ORIG.clear()
    guest = weapon_guest() if number == 5 else round_guest(guns=((0, 18), (2, 8)))
    ad = (A5 if number == 5 else A6)(guest)
    ctl = native.Controller.__new__(native.Controller)
    ctl.ad, ctl.lock = ad, threading.RLock()
    p = mods.R.snapshot(mods.Mem(ad))['player']
    epoch = (p['ptr'], p.get('generation', 7))
    ctl.ready = lambda: epoch
    yield number, mods, ctl, guest, epoch
    mods.ORIG.clear()


def test_status_is_read_only_and_enable_disable_have_actual_readback(ammo):
    number, mods, ctl, guest, epoch = ammo
    assert ctl.ammo_status()['enabled'] is False
    assert ctl.ad.writes == [] and not hasattr(ctl, 'heap')
    on = ctl.set_infinite_ammo(True, expected=epoch, allowed=lambda: True)
    assert on['state'] == 'confirmed' and on['verified'] and on['enabled']
    assert ctl.ammo_status()['enabled'] is True
    assert set(mods.ORIG) == {id(ctl.ad)}
    if number == 5:
        assert flag(guest, 2) == 1
    else:
        assert [(r, c) for _, r, c in mods.RE6Switch(ctl.ad).slots(epoch[0])] == [(18, 18), (8, 8)]
    assert ctl.set_infinite_ammo(False, expected=epoch)['enabled'] is False
    if number == 5:
        assert flag(guest, 2) == 0 and flag(guest, 0x15) == 1


@pytest.mark.parametrize('reason', ['owner', 'generation', 'type'])
def test_refusal_before_publication_writes_nothing(ammo, reason):
    _, _, ctl, _, epoch = ammo
    expected = (epoch[0], epoch[1] + 1) if reason == 'generation' else epoch
    with pytest.raises(N6.Unavailable):
        ctl.set_infinite_ammo('true' if reason == 'type' else True, expected=expected,
                              allowed=lambda: reason != 'owner')
    assert ctl.ad.writes == []


def test_owner_is_rechecked_between_individual_ammo_writes(ammo):
    _, _, ctl, _, epoch = ammo
    with pytest.raises(N6.Unavailable, match='input owner'):
        ctl.set_infinite_ammo(True, expected=epoch, allowed=lambda: not ctl.ad.writes)
    assert len(ctl.ad.writes) == 1


def test_silent_failed_write_never_reports_confirmed(ammo):
    _, _, ctl, _, epoch = ammo
    ctl.ad.write_memory = lambda *_: {'verified': False}
    with pytest.raises((N6.Uncertain, RuntimeError), match='confirmed'):
        ctl.set_infinite_ammo(True, expected=epoch)


def test_ammo_status_refuses_a_changed_life(ammo):
    _, _, ctl, _, epoch = ammo
    calls = iter((epoch, (epoch[0], epoch[1] + 1)))
    ctl.ready = lambda: next(calls)
    status = ctl.ammo_status()
    assert status['available'] is False and status['enabled'] is None
    assert not ctl.ad.writes
