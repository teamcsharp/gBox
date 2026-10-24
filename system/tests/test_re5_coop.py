import struct
from types import SimpleNamespace

from gbox.mercs.titles import re5_coop as C, re5_ps3 as R


class Memory:
    def __init__(self):self.data={}
    def put(self,a,raw):self.data.update({a+i:b for i,b in enumerate(raw)})
    def u(self,a,value):self.put(a,struct.pack('>I',value))
    def rd(self,a,n):return bytes(self.data.get(a+i,0) for i in range(n))


def world(second=False):
    m=Memory();manager=0x388369C0;m.u(R.S_PLAYER,manager);m.u(manager,C.PLAYER_MANAGER_VT)
    m.u(manager+0x38,2 if second else 1)
    for index in range(2 if second else 1):
        actor=0x303F7800+index*0x10000;m.u(manager+0x28+4*index,actor)
        m.put(actor+C.PLAYER_INDEX,bytes([index]));m.put(actor+R.P_POS,struct.pack('>3f',100+index,0,200))
        m.put(actor+R.P_HP,struct.pack('>hh',700-index*100,1000))
    return m


def test_read_only_participants_have_exact_native_slot_and_actor_index_provenance():
    m=world(True);before=dict(m.data);rows=C.participants(m)
    assert [(p['slot'],p['actor'],p['hp']) for p in rows]==[(1,0x303F7800,700),(2,0x30407800,600)]
    assert all(p['control']=='unknown' and p['native_actor_verified'] for p in rows)
    assert rows[1]['provenance']['actor_index_address']==0x30407800+0x2F14
    assert rows[1]['provenance']['slot_address']==0x388369C0+0x2C
    assert all(p['provenance']['read_only'] for p in rows) and m.data==before


def test_actor_existence_never_claims_human_assignment_or_ready_p2_policy():
    m=world(True);m.adapter=SimpleNamespace(teammate_pad_status=lambda:{'verified':True})
    status=C.readiness(m)
    assert status['p2_actor_verified'] and status['controller2_prepared']
    assert not status['p2_verified'] and not status['controller2_verified']
    assert not status['camera2_verified'] and not status['prompt2_verified']
    assert C.for_player(m,2) is None
    assert C.for_player(m,1) is None
    assert R.RE5PS3().participants(m)==C.participants(m)


def test_original_single_player_observation_is_available_without_inventing_partner():
    m=world();status=R.RE5PS3().readiness(m)
    assert status['human_observer_verified'] and not status['p2_actor_verified']
    assert len(status['active_players'])==1
    assert 'absent' in status['reason']
    stats={};assert R.RE5PS3().for_player(m,stats=stats) is None
    assert stats['teammate_runtime_reason']==status['reason']


def test_invalid_manager_or_slot_alias_or_wrong_actor_index_is_rejected():
    m=world(True);m.u(0x388369C0,0)
    assert C.participants(m)==[]
    m=world(True);m.u(0x388369C0+0x2C,0x303F7800)
    assert C.participants(m)==[]
    m=world(True);m.put(0x30407800+C.PLAYER_INDEX,b'\0')
    assert [p['slot'] for p in C.participants(m)]==[1]


def test_unreadable_and_invalid_positions_never_become_demonstration_points():
    m=world();m.put(0x303F7800+R.P_POS,struct.pack('>3f',float('nan'),0,0))
    assert C.participants(m)==[]
    m=world();m.rd=lambda a,n:(_ for _ in ()).throw(OSError('unmapped'))
    assert C.participants(m)==[]
