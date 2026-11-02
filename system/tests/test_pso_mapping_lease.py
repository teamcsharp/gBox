from copy import deepcopy
from types import SimpleNamespace
import pytest
from gbox import pso_coop_mapping as M
from gbox.desktop_input_lease import attach,InputLease
from test_pso_mapping_continuity import rig,SID,GAME


def attached(r):
    def emit(events,player=1):
        for event in events:
            if event.get('down',True):r.state['players'][player]['x']+=3
        return {'sent':len(events)}
    r.ad.send_input=lambda events,**kw:emit(events,1)
    r.ad.send_input_player=lambda events,player=2,**kw:emit(events,player)
    lease=attach(r.ad,'fixture-only')
    def hold(commands):
        for player,keys,seconds in commands:
            rows=[{'key':key,'down':True} for key in keys]
            r.ad.send_input_player(rows,player)
            r.ad.send_input_player([dict(row,down=False) for row in rows],player)
            r.events.append((player,keys,seconds))
    r.inputs.hold=hold
    return lease


def test_actual_lease_two_pad_probe_and_same_field_restart_retains_evidence(rig):
    r=rig;lease=attached(r)
    rows=r.prove()
    assert [row['moved'] for row in rows]==[3.,3.]
    assert len(r.events)==2 and M._receipt(r.ad) is not None
    assert M.diagnostics(r.ad)['controller_receipt_status']=='retained'
    r.state['floor']=1;r.ad._pso_verified_player_slots=set();r.events.clear()
    assert r.restore()['probe']==rows and not r.events
    assert r.ad._pso_verified_player_slots==set()
    assert M.diagnostics(r.ad)['controller_receipt_status']=='revalidated'
    assert lease.send is lease.__wrapped__


@pytest.mark.parametrize('change',['original','scoped','normalize','axis','replacement_lease','unknown_wrapper','keys'])
def test_changed_lease_or_underlying_route_cannot_reuse_proof(rig,change):
    r=rig;lease=attached(r);r.prove();r.events.clear();r.state['floor']=1
    if change=='original':lease.send=lease.__wrapped__=lambda events:None
    elif change=='scoped':r.ad.send_input_player=lambda events,player:None
    elif change=='normalize':lease.normalize=lambda player,key:(player,'other')
    elif change=='axis':lease.axis=lambda identity:('other',)
    elif change=='replacement_lease':
        original=lease.__wrapped__;scoped=r.ad.send_input_player.__wrapped__
        del r.ad._desktop_input_lease;r.ad.send_input=original;r.ad.send_input_player=scoped
        attach(r.ad,'fixture-only')
    elif change=='unknown_wrapper':
        r.ad.send_input=SimpleNamespace(__wrapped__=lease)
    elif change=='keys':r.ad.keys={'a':'changed'}
    assert r.restore() is None and not r.events
    assert M._receipt(r.ad) is None and r.ad._pso_verified_player_slots==set()
    assert M.diagnostics(r.ad)['controller_receipt_status']=='rejected'


def test_unknown_callable_never_attests_and_reports_reason_immediately(rig):
    r=rig
    class Unknown:
        def __call__(self,events):pass
    r.ad.send_input=Unknown()
    assert len(r.prove())==2 and M._receipt(r.ad) is None
    status=M.diagnostics(r.ad)
    assert status['controller_receipt_status']=='unavailable'
    assert 'Unsupported input callable' in status['controller_receipt_reason']
    assert not status['controller_receipt_retained']


def test_invalidated_reason_survives_absent_restore(rig):
    r=rig;attached(r);r.prove()
    M.invalidate(r.ad,'native_phase_7')
    assert r.restore() is None
    assert M.diagnostics(r.ad)=={'controller_receipt_status':'invalidated',
      'controller_receipt_reason':'native_phase_7','controller_receipt_retained':False,'controller_mapping_epoch':1}


def test_stop_with_lease_does_not_restore_active_permission(rig):
    r=rig;attached(r);r.prove();r.events.clear();r.stopped[0]=True
    assert r.restore() is None and not r.events
    assert M._receipt(r.ad) is not None and r.ad._pso_verified_player_slots==set()


def test_bound_method_access_does_not_change_fingerprint(rig):
    r=rig
    class Send:
        def emit(self,events):pass
        def scoped(self,events,player):pass
    send=Send();r.ad.send_input=send.emit;r.ad.send_input_player=send.scoped
    first=M._routing(r.ad)
    r.ad.send_input=send.emit;r.ad.send_input_player=send.scoped
    assert M._routing(r.ad)==first
    r.ad.send_input=Send().emit
    assert M._routing(r.ad)!=first


def test_unknown_function_wrapper_is_not_silently_unwrapped(rig):
    r=rig
    def wrapper(events):pass
    wrapper.__wrapped__=r.ad.send_input
    r.ad.send_input=wrapper
    with pytest.raises(ValueError,match='Unsupported input wrapper'):
        M._routing(r.ad)
