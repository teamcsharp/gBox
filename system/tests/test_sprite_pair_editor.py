import json
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import sprite_pair_editor as E,smb1_sprite_build as S,sprite_faces as F


@pytest.mark.parametrize('value',[{'crop':[0,0,0,1]},{'crop':[0,0,float('nan'),1]},{'scale':0},{'x':40},{'clip':'../../private'}])
def test_bounded_frame_transform(value):
    with pytest.raises(ValueError):E.FrameMap(**value)
    with pytest.raises(ValueError):E.PairProfile(frames={'26':{}})


def test_transform_defaults_match_native_fit_and_translation_preserves_blank_rows():
    from gbox.tas_sprites import fit
    image=Image.new('RGBA',(10,20),(20,80,240,255));image.putpixel((2,3),(255,0,0,255))
    expected=Image.new('RGBA',(16,32));expected.alpha_composite(fit(image,16,16),(0,16))
    assert np.array_equal(E.transform(image,16,E.FrameMap()),expected)
    result=np.array(E.transform(image,16,E.FrameMap(scale=2,x=4,mask=[0,.5,.5,1])))
    assert not result[:16,:,3].any() and not result[:,8:,3].any()
    with pytest.raises(ValueError,match='empty'):E.transform(image,0,E.FrameMap(crop=[.01,.01,.02,.02]))


def test_modified_smb_decode_requires_original_and_rejects_non_graphics_changes(monkeypatch):
    from gbox import tas
    original=bytearray(40976);original[100:112]=bytes.fromhex('221627182230271922372716')
    start=16+S.S.OFFSETS['PlayerGraphicsTable'];original[start:start+208]=bytes([1])*208
    for name in ('GroundPaletteData','WaterPaletteData','UndergroundPaletteData','CastlePaletteData'):
        off=16+S.S.OFFSETS[name];original[off:off+3]=bytes([0x3f,0,32])
    original=bytes(original)
    monkeypatch.setattr(tas,'smb_identity',lambda data:None if data==original else (_ for _ in ()).throw(ValueError('program differs')))
    monkeypatch.setattr(S.S,'_player_rows',lambda data:[list(data[S.S.OFFSETS['PlayerGraphicsTable']:S.S.OFFSETS['PlayerGraphicsTable']+8])]*26)
    monkeypatch.setattr(S.S,'_enemy_rows',lambda data:[[2]*6])
    changed=bytearray(original);changed[32784+16]=0xff;changed[start]=0xfc
    assert len(F.decoded(bytes(changed),F.SMB,reference=original))==26
    with pytest.raises(ValueError,match='program differs'):F.decoded(bytes(changed),F.SMB)
    changed[200]^=1
    with pytest.raises(ValueError,match='outside player'):F.decoded(bytes(changed),F.SMB,reference=original)


def test_pair_preview_snapshot_is_bound_to_profile_and_native_sources(tmp_path,monkeypatch):
    from gbox import tools,tas,sonic2d_sprites as D
    from gbox.store import Store
    cfg=SimpleNamespace(data_dir=tmp_path/'data',cache=tmp_path/'cache');store=Store(cfg.data_dir)
    store.catalog_get=lambda gid:{'game_id':gid,'title':'Native','platform':'nes','source_paths':['owned'],'format':'zip','profile_id':'test'}
    monkeypatch.setattr(tools,'rom_path',lambda *a:tmp_path/'owned')
    monkeypatch.setattr(tas,'rom_bytes',lambda p:b'original')
    image=Image.new('RGBA',(16,32),'blue')
    monkeypatch.setattr(S,'sonic_frames',lambda p:([image]*26,{'game_id':S.DONOR_ID,'rom_sha256':'source'}))
    monkeypatch.setattr(D,'read_rom',lambda p:(b'donor',{}))
    class Extractor:
        def __init__(self,*a):pass
        def plans(self,*a):return [{'name':'walk'},{'name':'run'}]
        def clip(self,*a):return {'images':[np.array(image)]*3,'index':{'frames':[{'duration_ms':100}]*3}}
    monkeypatch.setattr(D,'Extractor',Extractor)
    monkeypatch.setattr(S.S,'_player_rows',lambda p:[[0]*8]*26)
    monkeypatch.setattr(F,'decoded',lambda rom,gid,**kw:[(np.array(image),None,None,None)]*26)
    captured=[]
    def adapt(rom,frames,profile,selected):
        captured.append((profile.model_dump(),selected));return b'actual native rom',{'tiles_used':70,'tile_budget':91},[]
    monkeypatch.setattr(S,'adapt',adapt)
    app=FastAPI();E.routes(app,store,cfg,lambda:'operator');client=TestClient(app)
    url='/api/games/'+S.GAME_ID+'/sprite-pairs'
    templates=client.get(url).json();assert len(templates['target_frames'])==26 and templates['donor']['clips']==['walk','run']
    profile={'frames':{'0':{'clip':'run','frame':1,'scale':1.2,'x':1}}}
    response=client.post(url+'/preview',json={'profile':profile});assert response.status_code==200,response.text
    result=response.json();folder=cfg.data_dir/'sprite-pair-candidates'/result['id']
    assert (folder/'rom.bin').read_bytes()==b'actual native rom'
    saved=json.loads((folder/'candidate.json').read_text());assert saved['profile']['frames']['0']['scale']==1.2
    assert len(captured[-1][1])==1 and len(result['frames'])==26
    assert client.post(url+'/preview',json={'profile':profile}).json()['id']==result['id']
    job={'tool':'smb1_sprite_build','input':{'candidate':result['id']}}
    assert E.claim_reason({'build_sources':E.WRITER_SOURCES},job,cfg) is None
    assert 'idle worker' in E.claim_reason({'build_sources':{}},job,cfg)
    assert client.post(url+'/preview',json={'profile':{'frames':{'0':{'clip':'run','frame':99}}}}).status_code==422
    assert client.get('/api/games/unknown/sprite-pairs').status_code==422
