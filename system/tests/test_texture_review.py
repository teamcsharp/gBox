import copy,hashlib,io,json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import attachments as A, characters as C, texture_review as T
from gbox.store import Store


def model(path):
    data=T.png(Image.new('RGBA',(8,4),(80,110,180,125)))
    gl={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(data)}],
        'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(data)}],
        'images':[{'bufferView':0,'mimeType':'image/png'}],'textures':[{'source':0}],
        'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}},'normalTexture':{'index':0}}],
        'nodes':[{'name':'unchanged'}]}
    path.write_bytes(A.glb_bytes(gl,data));return gl,data


def prepare(path,store=None,job='review-job'):
    outputs={}
    def emit(name,data,kind):
        digest=hashlib.sha256(data).hexdigest();outputs[digest]=data
        if store:store.put_artifact(data,name,kind,{'job':job})
        return digest
    r=T.prepare(path,T.TextureIn(character='donor'),lambda im:im.resize((im.width*4,im.height*4)),emit)
    return r,outputs


def test_candidate_preserves_data_maps_alpha_source_and_geometry(tmp_path):
    path=tmp_path/'model.glb';original,_=model(path);before=path.read_bytes()
    result,files=prepare(path)
    gl,blob=A.read_gltf(path);candidate=tmp_path/'candidate.glb';candidate.write_bytes(files[result['candidate']])
    new,newblob=A.read_gltf(candidate)
    assert before==path.read_bytes() and newblob[:len(blob)]==blob
    assert new['nodes']==original['nodes'] and new['materials'][0]['normalTexture']=={'index':0}
    assert new['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index']!=0
    image=Image.open(io.BytesIO(files[result['images'][0]['after']]))
    assert image.size==(1024,512) and image.getpixel((10,10))[3]==125
    assert result['status']=='pending_approval'


def test_ai_is_not_silently_skipped_for_existing_large_maps():
    seen=[]
    image=Image.new('RGBA',(2048,1024))
    T.enhance(image,T.TextureIn(character='x',size=1024),lambda im:seen.append(im.size) or im.resize((im.width*2,im.height*2)))
    assert seen,'AI must run even when the source was already larger than the requested output'
    with pytest.raises(RuntimeError,match='not available'):
        T.enhance(Image.new('RGBA',(8,8)),T.TextureIn(character='x'),lambda _:(_ for _ in ()).throw(RuntimeError('not available')))


@pytest.fixture
def review(tmp_path):
    root=tmp_path/'characters';(root/'donor').mkdir(parents=True)
    source=root/'donor'/'model.glb';model(source)
    C.put_meta(root,{'slug':'donor','name':'Original','model':'model.glb','source':{},'rig':{'roles':{'head':'head'}},'targets':{'old':[]}})
    store=Store(tmp_path/'data');result,_=prepare(source,store);result.update(character='donor',name='Original')
    store.put('job','review-job',{'id':'review-job','tool':'texture_review','state':'succeeded','input':{'character':'donor'},'output':{'result':result}})
    app=FastAPI();jobs=[]
    class Job:
        def __init__(self,**kw):self.__dict__.update(kw)
    T.register(app,lambda:'operator',store,lambda:(C,root),lambda req,actor:jobs.append(req.__dict__) or {'id':'new-job'},Job)
    with TestClient(app) as client:yield SimpleNamespace(client=client,root=root,source=source,store=store,jobs=jobs,result=result)


def test_prepare_route_only_queues_and_reject_never_changes_donor(review):
    before=review.source.read_bytes()
    r=review.client.post('/api/characters/donor/texture-review',json={'character':'donor','size':2048})
    assert r.status_code==200 and review.jobs[0]['tool']=='texture_review' and review.jobs[0]['require_os']=='linux'
    assert review.client.get('/api/texture-reviews/review-job').json()['decision']['state']=='pending'
    assert review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'reject'}).json()['state']=='rejected'
    assert [p.name for p in review.root.iterdir()]==['donor'] and review.source.read_bytes()==before
    assert review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'accept'}).status_code==409


def test_accept_creates_separate_variant_only_once(review):
    before=review.source.read_bytes()
    response=review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'accept'})
    assert response.status_code==200,response.text
    row=response.json();assert row['state']=='accepted' and row['variant']!='donor'
    variant=C.get(review.root,row['variant'])
    assert variant['variant_of']=='donor' and 'targets' not in variant
    assert (review.root/row['variant']/'model.glb').read_bytes()==review.store.read_artifact(review.result['candidate'])
    assert review.source.read_bytes()==before
    assert review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'accept'}).json()==row
    assert review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'reject'}).status_code==409


def test_changed_source_cannot_be_approved(review):
    gl,blob=A.read_gltf(review.source);gl['nodes'][0]['name']='changed';review.source.write_bytes(A.glb_bytes(gl,blob))
    assert review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'accept'}).status_code==409
    assert len(list(review.root.iterdir()))==1


@pytest.mark.parametrize('size',[1024,2048,4096])
def test_requested_resolution_keeps_aspect_and_alpha(size):
    result=T.enhance(Image.new('RGBA',(8,4),(40,80,120,93)),
        T.TextureIn(character='x',size=size,backend='resample'),lambda _:pytest.fail('Resize-only must not invoke AI'))
    assert result.size==(size,size//2) and result.getpixel((0,0))[3]==93


def test_local_ai_graph_upload_fetch_and_model_discovery(monkeypatch):
    calls=[];pixels=T.png(Image.new('RGB',(32,16),'red'))
    class Reply:
        def __init__(self,data=None,content=b''):self.data=data;self.content=content
        def raise_for_status(self):pass
        def json(self):return self.data
    def get(url,**kw):
        calls.append(('GET',url,kw))
        if '/object_info/' in url:return Reply({'UpscaleModelLoader':{'input':{'required':{'model_name':['COMBO',{'options':['local.safetensors']}]}}}})
        if '/history/' in url:return Reply({'mine':{'status':{'completed':True},'outputs':{'4':{'images':[{'filename':'result.png','type':'output','subfolder':''}]}}}})
        return Reply(content=pixels)
    def post(url,**kw):
        calls.append(('POST',url,kw))
        return Reply({'name':'source.png','subfolder':'gbox'} if url.endswith('/upload/image') else {'prompt_id':'mine'})
    monkeypatch.setattr(T.httpx,'get',get);monkeypatch.setattr(T.httpx,'post',post)
    assert T.upscalers('http://local')==['local.safetensors']
    image=T.ai_upscale(Image.new('RGBA',(8,4)),'http://local','local.safetensors')
    assert image.size==(32,16)
    graph=next(c[2]['json']['prompt'] for c in calls if c[1].endswith('/prompt'))
    assert graph['1']['inputs']['image']=='gbox/source.png'
    assert graph['2']['inputs']['model_name']=='local.safetensors'
    assert graph['3']['class_type']=='ImageUpscaleWithModel'


def test_timeout_removes_only_its_own_pending_prompt(monkeypatch):
    posts=[];ticks=iter([0,901])
    class Reply:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    def post(url,**kw):
        posts.append((url,kw))
        return Reply({'name':'in.png'} if url.endswith('/upload/image') else {'prompt_id':'mine'})
    monkeypatch.setattr(T.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(T.httpx,'post',post)
    monkeypatch.setattr(T.httpx,'get',lambda *a,**kw:Reply({'queue_running':[[1,'other']], 'queue_pending':[[2,'mine'],[3,'other-pending']]}))
    with pytest.raises(TimeoutError,match='no candidate was approved'):
        T.ai_upscale(Image.new('RGB',(4,4)),'http://local','model')
    assert posts[-1]==('http://local/queue',{'json':{'delete':['mine']},'timeout':5})
