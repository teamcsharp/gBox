import json,struct
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import ff7_swap as S,psxdisc,characters,pe_swap

def record(name,lba,size,directory=False):
    name=name if isinstance(name,bytes) else name.encode()
    b=bytearray(33+len(name)+(len(name)%2==0));b[0]=len(b)
    struct.pack_into('<I',b,2,lba);struct.pack_into('>I',b,6,lba)
    struct.pack_into('<I',b,10,size);struct.pack_into('>I',b,14,size)
    b[25]=2 if directory else 0;b[28:32]=bytes.fromhex('01000001');b[32]=len(name);b[33:33+len(name)]=name
    return b

def raw_disc(path):
    b=bytearray(32*2352)
    for i in range(32):b[i*2352+15]=2
    pvd=bytearray(2048);pvd[0]=1;pvd[1:6]=b'CD001';pvd[6]=1;pvd[156:190]=record(b'\0',20,2048,True)
    b[16*2352+24:16*2352+24+2048]=pvd
    entries=record(b'\0',20,2048,True)+record(b'\1',20,2048,True)+record('A.BCX;1',21,16)+record('B.BCX;1',22,16)
    b[20*2352+24:20*2352+24+len(entries)]=entries
    b[21*2352+24:21*2352+40]=b'A'*16;b[22*2352+24:22*2352+40]=b'B'*16
    path.write_bytes(b);return path

def test_two_prepared_members_survive_and_source_is_unchanged(tmp_path,monkeypatch):
    base=raw_disc(tmp_path/'base.bin');before=base.read_bytes()
    cfg=SimpleNamespace(cache=tmp_path/'cache');game={'game_id':'6703ee6f461a2ea5'}
    meta={'slug':'mario','name':'Mario','model':'mario.gltf','rig':{'roles':{'hip':'hip'}}}
    monkeypatch.setattr(pe_swap,'base_bin',lambda *a:base);monkeypatch.setattr(characters,'_blender',lambda *a:None)
    def prepare(*args,**kw):
        assert kw['prepare_only'] and Path(args[0])==base and not Path(args[5]).exists()
        key,payload=('A.BCX',b'tifa') if kw['field_file']=='TIFA' else ('B.BCX',b'cid')
        return {'writes':[(key,payload)],'field':{},'battle':{}}
    monkeypatch.setattr(S,'build',prepare)
    result=S.build_cast(cfg,game,[('tifa',meta),('cid',meta)],'cast',root=tmp_path)
    output=Path(result['detail']['bin']);disc=psxdisc.RawBin(output,writable=False)
    try:assert disc.read('A.BCX').startswith(b'tifa') and disc.read('B.BCX').startswith(b'cid')
    finally:disc.close()
    assert base.read_bytes()==before and result['detail']['readback_verified']
    assert all(x['status']=='built' for x in result['slots'].values())
    old=output.read_bytes();second=S.build_cast(cfg,game,[('tifa',meta)],'cast',root=tmp_path)
    assert second['mod']!=result['mod'] and output.read_bytes()==old
    manifest=json.loads((output.parent/'.gbox-mod.json').read_text());assert manifest['image'].endswith('.cue')

def test_failed_write_never_publishes_and_preserves_source(tmp_path,monkeypatch):
    base=raw_disc(tmp_path/'base.bin');before=base.read_bytes();out=tmp_path/'out.bin'
    original=psxdisc.RawBin.write_file
    def fail(self,name,offset,data):
        if name=='B.BCX':raise ValueError('second write failed')
        return original(self,name,offset,data)
    monkeypatch.setattr(psxdisc.RawBin,'write_file',fail)
    with pytest.raises(ValueError,match='second write'):S._write_prepared(base,out,{'A.BCX':b'changed','B.BCX':b'changed'})
    assert not out.exists() and not list(tmp_path.glob('*.partial')) and base.read_bytes()==before

def test_readback_mismatch_rejected(tmp_path,monkeypatch):
    base=raw_disc(tmp_path/'base.bin');out=tmp_path/'out.bin'
    monkeypatch.setattr(psxdisc.RawBin,'write_file',lambda *a:0)
    with pytest.raises(ValueError,match='readback'):S._write_prepared(base,out,{'A.BCX':b'changed'})
    assert not out.exists()

def test_refuses_existing_output_source_alias_and_oversize(tmp_path):
    base=raw_disc(tmp_path/'base.bin');out=tmp_path/'old.bin';out.write_bytes(b'keep')
    for target in (base,out):
        with pytest.raises(ValueError):S._write_prepared(base,target,{'A.BCX':b'new'})
    with pytest.raises(ValueError,match='exceeds'):S._write_prepared(base,tmp_path/'new.bin',{'A.BCX':b'x'*17})
    assert out.read_bytes()==b'keep'

def test_cached_member_uses_slot_specific_name(tmp_path,monkeypatch):
    from gbox import sm64_swap
    ctx=SimpleNamespace(config=SimpleNamespace(cache=tmp_path),progress=lambda *a:None)
    inp=SimpleNamespace(slot='tifa',rebuild=False,launch=False,session_id=None)
    seen=[];monkeypatch.setattr(sm64_swap,'_have_mod',lambda ctx,gid,name:seen.append(name) or True)
    result=S.use(ctx,{'slug':'mario','name':'Mario'},{'game_id':'6703ee6f461a2ea5'},inp)
    assert seen==[S.mod_name({'slug':'mario'},'tifa')] and result['mod']==seen[0]

def test_remote_member_preserves_slot(tmp_path,monkeypatch):
    from gbox import sm64_swap
    ctx=SimpleNamespace(config=SimpleNamespace(cache=tmp_path),progress=lambda *a:None)
    inp=SimpleNamespace(slot='tifa',rebuild=True,launch=False,session_id=None)
    monkeypatch.setattr(characters,'library_root',lambda _:tmp_path/'missing')
    monkeypatch.setattr(characters,'_api',lambda *a,**k:[{'id':'linux','os':'linux'}])
    def job(ctx,tool,data,*a):
        assert data['slot']=='tifa' and data['launch'] is False
        return {'state':'succeeded','output':{'result':{'status':'built','mod':'tifa_remote'}}}
    monkeypatch.setattr(characters,'_job',job)
    result=S.use(ctx,{'slug':'mario','name':'Mario'},{'game_id':'6703ee6f461a2ea5'},inp)
    assert result['mod']=='tifa_remote'
