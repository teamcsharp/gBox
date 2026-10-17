import base64,hashlib,io,json,struct
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import photo_skin as P, re4_photo_skin as N, re4gc_models as R, characters as C, attachments as A, cast_swap as CS
from gbox.store import Store
from tests.test_texture_review import model
from tests.test_cast_swap import entry, ROLES, JGR


def settings(**kw):return P.Placement(photo='a'*64,maps=[0],**kw)


def test_projection_preserves_alpha_and_outside_pixels():
    original=Image.new('RGBA',(64,64),(10,20,30,83));photo=Image.new('RGBA',(30,40),(210,40,50,255))
    out=P.project(original,photo,settings(quad=[[.25,.25],[.75,.25],[.75,.75],[.25,.75]],feather=0))
    assert out.getpixel((32,32))==(210,40,50,83)
    assert out.getpixel((0,0))==original.getpixel((0,0))


@pytest.mark.parametrize('kw',[{'crop':[0,0,0,1]},{'quad':[[0,0],[1,1],[1,0],[0,1]]},{'quad':[[0,0],[2,0],[1,1],[0,1]]},{'maps':[-1]}])
def test_invalid_crop_and_folded_uv_are_rejected(kw):
    with pytest.raises(ValueError):P.Placement(**({'photo':'a'*64,'maps':[0]}|kw))


def test_candidate_changes_only_color_binding_not_mesh_rig_or_data_maps(tmp_path):
    src=tmp_path/'base.glb';original,blob=model(src);before=src.read_bytes();files={}
    def emit(n,d,k):h=hashlib.sha256(d).hexdigest();files[h]=d;return h
    result=P.prepare(src,Image.new('RGB',(20,20),'red'),settings(),emit)
    dest=tmp_path/'candidate.glb';dest.write_bytes(files[result['candidate']]);gl,newblob=A.read_gltf(dest)
    assert src.read_bytes()==before and newblob[:len(blob)]==blob
    assert gl['nodes']==original['nodes'] and gl['materials'][0]['normalTexture']=={'index':0}
    assert gl['materials'][0]['pbrMetallicRoughness']['baseColorTexture']!={'index':0}
    assert result['status']=='pending'


@pytest.fixture
def api(tmp_path,monkeypatch):
    root=tmp_path/'characters';(root/'base').mkdir(parents=True);model(root/'base/model.glb')
    C.put_meta(root,{'slug':'base','name':'Original','model':'model.glb','source':{'game_title':'Source'},'rig':{'roles':ROLES},
                   'rigs':{'cached':'old.gltf'},'targets':{'old':[]},'native_player':True})
    monkeypatch.setattr(C,'render_preview',lambda *a,**kw:(_ for _ in ()).throw(ValueError('synthetic model; no renderer')))
    store=Store(tmp_path/'data');app=FastAPI();P.register(app,lambda:'operator',store,lambda:(C,root));c=TestClient(app)
    encoded=base64.b64encode(P.png(Image.new('RGB',(20,30),'red'))).decode()
    photo=c.post('/api/photo-skins/photos',json={'data_url':'data:image/png;base64,'+encoded}).json()['photo']
    return c,store,root,photo


def test_approval_is_explicit_idempotent_and_drops_cached_native_rigs(api):
    c,s,root,photo=api;before=(root/'base/model.glb').read_bytes()
    r=c.post('/api/characters/base/photo-skins',json={'name':'Bla','photo':photo,'maps':[0]});assert r.status_code==200,r.text
    review=r.json();assert len(list(root.iterdir()))==1
    row=c.post('/api/photo-skins/'+review['id']+'/decision',json={'decision':'accept'}).json()
    m=C.get(root,row['variant']);assert m['variant_of']=='base' and m['photo_skin_approval']['images']
    assert not any(k in m for k in ('rigs','targets','native_player'))
    assert before==(root/'base/model.glb').read_bytes()
    assert c.post('/api/photo-skins/'+review['id']+'/decision',json={'decision':'accept'}).json()==row
    assert c.post('/api/photo-skins/'+review['id']+'/decision',json={'decision':'reject'}).status_code==409


def test_reject_and_changed_source_never_import_candidate(api):
    c,s,root,photo=api
    row=c.post('/api/characters/base/photo-skins',json={'photo':photo,'maps':[0]}).json()
    assert c.post('/api/photo-skins/'+row['id']+'/decision',json={'decision':'reject'}).json()['status']=='rejected'
    row=c.post('/api/characters/base/photo-skins',json={'photo':photo,'maps':[0]}).json()
    gl,blob=A.read_gltf(root/'base/model.glb');gl['nodes'][0]['name']='changed';(root/'base/model.glb').write_bytes(A.glb_bytes(gl,blob))
    assert c.post('/api/photo-skins/'+row['id']+'/decision',json={'decision':'accept'}).status_code==409
    assert len(list(root.iterdir()))==1


def test_native_texture_patch_keeps_geometry_pack_size_and_unrelated_bytes():
    im=R.tpl_image_from_rgba(np.asarray(Image.new('RGBA',(8,8),(90,120,170,255))))
    tpl=R.tpl_write([im]);dat=R.dat_write([('BIN',b'geometry weights and bones'*20),('TPL',tpl),('MOT',b'animation'*20)])
    entry=bytearray(32);struct.pack_into('>I',entry,0,0)
    raw=R.udas_write([{'type':0,'entry':bytes(entry),'data':dat}])
    replacement=Image.new('RGBA',(8,8),(200,40,50,255))
    out,rows=N.patch_pack(raw,{((8,8),im.rgba().tobytes()):replacement})
    assert rows and out!=raw and len(out)==len(raw)
    a,b=R.ModelPack(raw),R.ModelPack(out)
    assert a.items[0]==b.items[0] and a.items[2]==b.items[2]


def test_locked_photo_lead_survives_seeds_and_supporting_pool_excludes_it():
    chars=[entry('donor_a','A','Metal Gear Solid','psx'),entry('donor_b','B','Metal Gear Solid','psx'),
        entry('bla_photo','Bla','Resident Evil 4','gamecube',variant_of='leon',photo_skin_approval={'review':'accepted'})]
    slots=[{'slot':'player','kind':'player'},{'slot':'id:1','kind':'character'}]
    for seed in ['a','b','c']:
        p=CS.plan(JGR,chars,'Metal Gear Solid',mapping='random',seed=seed,slot_list=slots,lead_character='bla_photo')
        assert p['assignments'][0]['character']=='bla_photo'
        assert p['assignments'][1]['character']!='bla_photo'
        assert p['locked_lead']=={'slot':'player','character':'bla_photo'}
    with pytest.raises(ValueError,match='lead slot'):
        CS.plan(JGR,chars,'Metal Gear Solid',slot_list=[{'slot':'id:1','kind':'character'}],lead_character='bla_photo')


def test_demo_plans_expose_exact_version_and_combined_cast_gaps():
    for g,state in [({'game_id':'78ab9efa2e310db4','title':'RE4'},'unsupported_cast'),
        ({'game_id':'1fd42f50b10252e6','title':'Vice City'},'needs_install_validation'),
        ({'game_id':'18e7103191eed582','title':'GoldenEye'},'needs_native_writer')]:
        assert P.demo_plan(g,[],'bla','Metal Gear Solid','seed')['state']==state


def test_old_worker_cannot_silently_drop_photo_contract_or_lead():
    j={'tool':'characters','input':{'op':'cast_swap','lead_character':'bla'}}
    assert 'refreshed worker' in P.claim_reason({'build_sources':{}},j)
    assert P.claim_reason({'build_sources':P.CONTRACT_SOURCES},j) is None
    assert P.claim_reason({}, {'tool':'characters','input':{'op':'use','character':'leon_photo_123'}})
    assert P.claim_reason({}, {'tool':'characters','input':{'op':'use','character':'leon'}}) is None
