"""The pose viewer reads exact original/overlay bytes and never launches or creates builds."""
import json
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from gbox import decrypt_lab as L, mt_arc, switch_mods as S
from gbox.config import Config

TID,GID='010018100CD46000','52d15709be0fda1a'
INNER='nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc'


@pytest.fixture
def panel(tmp_path,monkeypatch):
    cfg=Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache')
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    root=tmp_path/'gBox_alt'/'switch'/'romfs'/TID
    path=root/INNER;path.parent.mkdir(parents=True)
    native=mt_arc.build(mt_arc.Arc(7,[mt_arc.Entry(r'pawn\pl\pl00\motion\pl00wp00',1,10,0,0,zlib.compress(b'LMT\0native'))]))
    path.write_bytes(native)
    calls=[]
    motion=SimpleNamespace(list_clips=lambda raw:[{'index':3,'frame_count':200,'supported':True},
                                                {'index':4,'frame_count':20,'supported':False,'reason':'Unsupported codec 99'},
                                                {'index':5,'frame_count':30,'supported':False,'raw_fk_supported':True,'reason':'Game IK is required'}])
    def sample(a,b,lmt,**kwargs):
        calls.append((a,b,lmt,kwargs))
        return {'fps':30,'clip':{'animation_index':kwargs['animation_index']},'native':{},'candidate':{}}
    motion.sample_compare=sample
    monkeypatch.setitem(sys.modules,'gbox.mtf_motion',motion)
    import gbox
    monkeypatch.setattr(gbox,'mtf_motion',motion,raising=False)
    rows=[(GID,json.dumps({'serial':TID}))]
    store=SimpleNamespace(db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchall=lambda:rows)))
    app=FastAPI();L.install(app,store,cfg,lambda:None)
    endpoint=next(r.endpoint for r in app.routes if r.path=='/api/decrypt-lab/model-compare')
    return cfg,root,native,calls,endpoint


def request(**kw):
    return L.ModelCompareIn(title='re5_switch',**kw)


def test_catalog_is_read_only_and_names_native_motion_indices(panel):
    cfg,_,_,calls,endpoint=panel
    result=endpoint(request(op='list'))
    assert result['builds']==[] and result['motions'][0]['entry_index']==0
    assert result['motions'][0]['clips'][1]['reason']=='Unsupported codec 99'
    assert not calls and not S.mods_root(cfg).exists()


def test_catalog_decodes_only_the_selected_motion(panel,monkeypatch):
    _,root,_,_,endpoint=panel
    import gbox
    names=['pl00face','pl00wp00']
    native=mt_arc.build(mt_arc.Arc(7,[mt_arc.Entry('pawn\\pl\\pl00\\motion\\'+name,1,10,0,0,zlib.compress(b'LMT\0'+name.encode())) for name in names]))
    (root/INNER).write_bytes(native)
    decoded=[]
    monkeypatch.setattr(gbox.mtf_motion,'list_clips',lambda raw:decoded.append(raw) or [])
    result=endpoint(request(op='list'))
    assert result['selected_animation_entry']==1
    assert decoded==[b'LMT\0pl00wp00'] and len(result['motions'])==2
    result=endpoint(request(op='list',animation_entry=0))
    assert result['selected_animation_entry']==0
    assert decoded==[b'LMT\0pl00wp00',b'LMT\0pl00face']


def test_sampling_uses_newest_pending_candidate_and_exact_same_native_frames(panel):
    cfg,root,native,calls,endpoint=panel
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':b'applied'}},create={'title_id':TID})
    pending=mt_arc.build(mt_arc.Arc(7,[mt_arc.Entry(r'pawn\pl\pl00\motion\pl00wp00',1,10,0,0,zlib.compress(b'LMT\0candidate'))]))
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':pending}},in_use=True)
    folder=S.build_dir(cfg,GID,'candidate')
    before={str(p.relative_to(folder)):p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    result=endpoint(request(build='candidate',animation_entry=0,animation_index=3,start_frame=195,frame_count=60))
    assert calls[0][:3]==(native,pending,b'LMT\0native')
    assert calls[0][3]['frames']==[195,196,197,198,199]
    assert calls[0][3]['candidate_lmt_bytes']==b'LMT\0candidate'
    assert calls[0][3]['raw_fk'] is False
    assert result['frame_indices']==[195,196,197,198,199]
    assert result['source']['build']=='candidate'
    assert {str(p.relative_to(folder)):p.read_bytes() for p in folder.rglob('*') if p.is_file()}==before
    assert (root/INNER).read_bytes()==native


def test_bind_pose_is_not_claimed_to_be_an_animation(panel):
    cfg,_,_,calls,endpoint=panel
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':b'candidate'}},create={'title_id':TID})
    endpoint(request(build='candidate'))
    assert calls[0][3]['animation_index'] is None and calls[0][3]['frames']==[0]


@pytest.mark.parametrize('kwargs,status,reason',[
    ({'build':'absent'},404,'existing RE5 overlay'),
    ({'build':'../outside'},404,'existing RE5 overlay'),
    ({'op':'list','arc_path':'../outside.arc'},409,'Chris'),
    ({'op':'list','model_name':'other'},409,'Chris'),
    ({'op':'list','frame_count':61},400,'bounded'),
])
def test_invalid_comparison_never_creates_a_build(panel,kwargs,status,reason):
    cfg,_,_,calls,endpoint=panel
    with pytest.raises(HTTPException,match=reason) as error:endpoint(request(**kwargs))
    assert error.value.status_code==status
    assert not calls and not S.mods_root(cfg).exists()


def test_unsupported_or_out_of_range_animation_fails_before_sampling(panel):
    cfg,_,_,calls,endpoint=panel
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':b'candidate'}},create={'title_id':TID})
    for kwargs,reason in [({'animation_index':4},'Unsupported codec'),({'animation_index':3,'start_frame':200},'outside'),({'animation_entry':9},'motion entry')]:
        with pytest.raises(HTTPException,match=reason):endpoint(request(build='candidate',**kwargs))
    assert not calls


def test_game_ik_clip_requires_explicit_diagnostic_preview(panel):
    cfg,_,native,calls,endpoint=panel
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':native}},create={'title_id':TID})
    with pytest.raises(HTTPException,match='Game IK'):endpoint(request(build='candidate',animation_index=5))
    assert not calls
    endpoint(request(build='candidate',animation_index=5,raw_fk=True))
    assert calls[0][3]['raw_fk'] is True
    with pytest.raises(HTTPException,match='Unsupported codec'):endpoint(request(build='candidate',animation_index=4,raw_fk=True))
    assert len(calls)==1


def test_candidate_motion_entry_must_match_native_identity(panel):
    cfg,_,_,calls,endpoint=panel
    candidate=mt_arc.build(mt_arc.Arc(7,[mt_arc.Entry(r'pawn\pl\pl00\motion\wrong',1,10,0,0,zlib.compress(b'LMT\0candidate'))]))
    S.write_files(cfg,GID,'candidate',{'romfs/'+INNER:{'bytes':candidate}},create={'title_id':TID})
    with pytest.raises(HTTPException,match='matching native motion'):endpoint(request(build='candidate',animation_index=3))
    assert not calls
