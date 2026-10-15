import struct

import numpy as np
import pytest
from PIL import Image

from gbox import sprite_faces as F,smb1_sprite_build as S


@pytest.mark.parametrize('value',[{'crop':[0,0,0,1]},{'crop':[0,0,float('nan'),1]},
    {'rectangles':{'../file':[0,0,1,1]}},{'frames':[1,1]},{'opacity':0}])
def test_mapping_refuses_invalid_or_unbounded_geometry(value):
    with pytest.raises(ValueError):F.Mapping(**value)


def test_native_photo_patch_preserves_shared_body_pixels_and_updates_genesis_checksum(monkeypatch):
    colors=np.array([[0,0,0,0],[255,255,255,255],[0,0,0,255]],np.uint8)
    rgba=np.tile(colors[1],(4,4,1));refs=np.arange(16,dtype=np.int64).reshape(4,4)+0x600
    other=np.full((4,4),-1,np.int64);other[0,0]=refs[0,0]
    monkeypatch.setattr(F,'decoded',lambda *args:[(rgba,refs,colors,np.ones((4,4),np.uint8)),(rgba,other,colors,np.ones((4,4),np.uint8))])
    rom=bytes([0x11])*1024
    mapping=F.Mapping(crop=[0,0,1,1],flip=False,shape='rectangle',feather=0,frames=[0],rectangles={'0':[0,0,1,1]})
    out,report=F.apply(rom,F.SONIC[0],Image.new('RGB',(32,32),'black'),mapping)
    assert report['changed_pixels']==15 and report['shared_pixels_preserved']==1
    assert out[0x300]>>4==1,'a head pixel aliased by an unselected/body frame is untouched'
    changed={i for i,(a,b) in enumerate(zip(rom,out)) if a!=b}
    assert changed<={0x18e,0x18f,*range(0x300,0x308)}
    assert struct.unpack_from('>H',out,0x18e)[0]==sum(struct.unpack('>256H',out[0x200:]))&0xffff


def test_automatic_face_mask_does_not_stretch_to_disconnected_hands():
    rgba=np.ones((32,16,4),np.uint8)*255;ids=np.zeros((32,16),np.uint8)
    ids[2:9,5:12]=2;ids[16:19,0:3]=2
    rect=F.default_rect(rgba,ids,F.SMB)
    assert rect==[5/16,2/32,12/16,9/32]


def test_nes_bitplanes_encode_all_two_bit_colors():
    a=np.tile(np.array([0,1,2,3,0,1,2,3],np.uint8),(8,1));data=S.encode_tile(a)
    restored=np.array([[((data[y]>>(7-x))&1)|(((data[y+8]>>(7-x))&1)<<1) for x in range(8)] for y in range(8)])
    assert np.array_equal(a,restored)
    with pytest.raises(ValueError):S.encode_tile(np.full((8,8),4))


def test_layers_translate_rotate_and_respect_visibility_and_blend():
    rgba=np.full((16,16,4),255,np.uint8);rgba[:,:,:3]=100
    photo=Image.new('RGB',(16,16),(200,40,20))
    m=F.Mapping(crop=[0,0,1,1],flip=False,shape='rectangle',feather=0,
        layers=[F.Layer(blend='multiply'),F.Layer(visible=False)])
    result,coverage=F.composite(rgba,photo,m,[.25,.25,.75,.75])
    assert np.allclose(result[8,8],[100*200/255,100*40/255,100*20/255])
    assert np.allclose(result[0,0],100) and coverage[0,0]==0
    m.layers[0].offset=[.5,0];m.layers[0].rotation=90
    translated,weight=F.composite(rgba,photo,m,[.25,.25,.75,.75])
    assert np.allclose(translated[8,8],100) and weight[8,8]==0
    with pytest.raises(ValueError):F.Layer(offset=[float('nan'),0])
    with pytest.raises(ValueError):F.Mapping(layers=[F.Layer()]*9)


def test_projection_changes_uvs_without_changing_native_positions_or_normals(monkeypatch):
    from gbox import sm64_photo_projection as N,sm64_writer as W,sm64_swap as S
    triangle=tuple((tuple(p),(0,1,0),(0,0)) for p in [(30,60,-20),(70,80,20),(90,50,0)])
    parts={3:[(0,triangle)]};mats=[{'diffuse':(254,193,121),'ambient':(127,96,60),'tex':None}]
    model={'joints':[{'tris':[1]}]};captured={}
    monkeypatch.setattr(N,'source',lambda rom:(model,parts,mats,[0]))
    monkeypatch.setattr(N,'atlas',lambda rom:np.full((64,32,4),255,np.uint8))
    monkeypatch.setattr(S,'check_rom',lambda rom:None)
    def inject(rom,edited,materials):captured.update(parts=edited,mats=materials);return b'edited'
    monkeypatch.setattr(W,'inject',inject)
    m=F.Mapping(projection=F.Projection(yaw=25,pitch=10))
    out,report=N.apply(b'rom',Image.new('RGB',(16,16),'red'),m)
    assert out==b'edited' and report['geometry_decimation'] is False
    actual=captured['parts'][3][0][1]
    assert [(p,n) for p,n,t in actual]==[(p,n) for p,n,t in triangle]
    assert actual[0][2]!=N.uv(triangle[0][0])
    assert report['projection_target']=='gameplay' and 'unchanged' in report['boot_screen']


def test_live_preview_storage_is_bounded_and_submitted_candidates_are_pinned(tmp_path):
    import json
    from test_build_quarantine import Memory
    store=Memory();pinned='f'*32
    store.put('game_build_request','request',{'mapping':{'candidate':pinned}})
    for i in range(40):
        folder=tmp_path/(pinned if i==0 else f'{i:032x}');folder.mkdir()
        (folder/'rom.bin').write_bytes(b'rom');(folder/'candidate.json').write_text(json.dumps({'id':folder.name}))
    F.prune_candidates(tmp_path,store,keep=f'{39:032x}')
    assert (tmp_path/pinned/'rom.bin').exists()
    assert len(list(tmp_path.glob('*/candidate.json')))<=34


def test_loading_images_decode_real_roms_and_keep_the_immutable_build_untouched(tmp_path,monkeypatch):
    import io,json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from gbox.store import Store
    from gbox import tools,tas,sonic2d_sprites as D
    cfg=SimpleNamespace(cache=tmp_path/'cache',data_dir=tmp_path/'data');store=Store(cfg.data_dir)
    store.catalog_get=lambda gid:{'game_id':gid,'title':'Native player','platform':'nes','source_paths':['owned.zip'],'format':'zip','profile_id':'test'}
    monkeypatch.setattr(tools,'rom_path',lambda *a:tmp_path/'owned.zip')
    monkeypatch.setattr(tas,'rom_bytes',lambda p:b'original')
    monkeypatch.setattr(D,'read_rom',lambda p:(b'donor',{}))
    calls=[]
    def frames(rom,gid):
        calls.append((rom,gid));color={'original':(255,0,0,255),'patched':(0,0,255,255),'donor':(0,255,0,255)}[rom.decode()]
        return [(np.tile(np.array(color,np.uint8),(4,4,1)),None,None,None)]*2
    monkeypatch.setattr(F,'decoded',frames)
    folder=cfg.cache/'mods'/F.SMB/'sonic';folder.mkdir(parents=True)
    (folder/'game.nes').write_bytes(b'patched')
    marker=folder/'.gbox-mod.json';meta={'game_id':F.SMB,'writer':'gbox.smb1_sprite_build','image':'game.nes'}
    marker.write_text(json.dumps(meta));original_marker=marker.read_bytes()
    app=FastAPI();F.routes(app,store,cfg,lambda:'operator');client=TestClient(app)
    pair=F.loading_preview(F.SMB,'sonic',meta)
    for key,color in [('original',(255,0,0,255)),('result',(0,0,255,255)),('source',(0,255,0,255))]:
        response=client.get(pair[key]['preview_url']);assert response.status_code==200,response.text
        assert Image.open(io.BytesIO(response.content)).getpixel((0,0))==color
    n=len(calls);assert client.get(pair['result']['preview_url']).status_code==200 and len(calls)==n
    assert marker.read_bytes()==original_marker and (folder/'game.nes').read_bytes()==b'patched'
    assert client.get(pair['result']['preview_url'].replace('after.png','other.png')).status_code==404
    marker.write_text(json.dumps(meta|{'image':'../private.nes'}));assert client.get(pair['result']['preview_url']).status_code==404
