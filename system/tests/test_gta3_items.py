"""Inventory guards and native-call transactions; native execution has separate evidence."""
import hashlib
import struct

import pytest

from gbox import gta3_items as I,gta_mods_tool as G
from gbox.registry import Unsupported


class Adapter:
    def __init__(self):self.ram=bytearray(0x2000000);self.writes=[]
    def read_memory(self,a,n):return self.ram[a:a+n]
    def write_memory(self,a,data):self.writes.append((a,bytes(data)));self.ram[a:a+len(data)]=data


def fixture(monkeypatch):
    ad=Adapter();ped=0x200000
    monkeypatch.setattr(I,'check',lambda m,g:(ped,{'fn':{'RequestModel':10,'LoadAllRequestedModels':20}}))
    monkeypatch.setattr(G,'install',lambda m,g:{'installed':True})
    monkeypatch.setattr(G,'player_ped',lambda m,g:ped)
    batches=[]
    def call(m,batch,timeout):
        batches.append(batch)
        for c in batch:
            if c['fn']==I.GIVE_WEAPON:
                slot=c['a1'];at=ped+I.SLOT_BASE+slot*I.SLOT_SIZE
                ad.ram[at:at+20]=struct.pack('<5I',slot,0,0,c['a2'],0)
        return [0]*len(batch)
    monkeypatch.setattr(G,'call',call)
    return ad,ped,batches


def test_all_weapons_uses_native_streaming_and_grant_routines_with_readback(monkeypatch):
    ad,ped,batches=fixture(monkeypatch);ad.ram[ped+I.CURRENT]=3
    result=I.execute(ad,{},'all_weapons',ammo=1234)
    assert result['verified'] and result['missing']==[]
    grants=[c for b in batches for c in b if c['fn']==I.GIVE_WEAPON]
    assert [c['a1'] for c in grants]==list(range(1,12))
    assert all(c['a0']==ped for c in grants)
    assert all(len(b)<=G.CQ_MAX for b in batches)
    assert all(r['present'] for r in result['inventory'][1:12])
    assert result['inventory'][3]['equipped']
    assert ad.ram[ped+I.CURRENT]==3


def test_no_automatic_retry_when_another_command_is_pending(monkeypatch):
    ad,ped,batches=fixture(monkeypatch)
    struct.pack_into('<I',ad.ram,G.DATA+G.D_CQ_N,1)
    with pytest.raises(RuntimeError,match='pending'):I.execute(ad,{},'give','pistol')
    assert batches==[]


def test_detonator_refused_before_any_native_install_or_write(monkeypatch):
    ad,ped,batches=fixture(monkeypatch)
    monkeypatch.setattr(G,'install',lambda *_:pytest.fail('Must reject before install'))
    with pytest.raises(Unsupported,match='remote-car-bomb'):I.execute(ad,{},'give','detonator')
    assert not ad.writes and not batches


def test_player_change_stops_before_queueing(monkeypatch):
    ad,ped,batches=fixture(monkeypatch);monkeypatch.setattr(G,'player_ped',lambda *_:ped+0x100)
    with pytest.raises(RuntimeError,match='player changed'):I.execute(ad,{},'give','bat')
    assert not batches


def test_missing_native_grant_is_reported_unverified(monkeypatch):
    ad,ped,batches=fixture(monkeypatch);monkeypatch.setattr(G,'call',lambda *a,**kw:[0])
    result=I.execute(ad,{},'give','pistol')
    assert result['verified'] is False and result['missing']==['Pistol']


def test_exact_code_fingerprint_and_player_pointer_required(monkeypatch):
    ad=Adapter();m=G.Mem(ad);addr=0x100000;blob=b'owned executable bytes'
    ad.ram[addr:addr+len(blob)]=blob
    monkeypatch.setattr(I,'FINGERPRINTS',((addr,len(blob),hashlib.sha256(blob).hexdigest()),))
    monkeypatch.setattr(G,'player_ped',lambda *_:0x200000)
    game={'platform':'ps2','game_id':'265819390074bb4e'}
    assert I.check(m,game)[0]==0x200000
    ad.ram[addr]^=1
    with pytest.raises(Unsupported,match='does not match'):I.check(m,game)
    with pytest.raises(Unsupported,match='PS2'):I.check(m,game|{'platform':'windows_native'})


def test_uninitialized_native_inventory_refused():
    ad=Adapter();ped=0x200000
    struct.pack_into('<I',ad.ram,ped+I.SLOT_BASE+2*I.SLOT_SIZE,0xFFFFFFFF)
    with pytest.raises(Unsupported,match='not initialized'):I.inventory(G.Mem(ad),ped)
