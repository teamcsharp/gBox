from pathlib import Path
import numpy as np
import pytest
from gbox import sm64_swap as S, ninja_swap as N, doa2_swap as D, ff7_swap as F


def geometry():
    return [{'pos':np.array([[0.,0,0],[1,0,0],[0,1,0]]),'nrm':np.tile([0.,0,1],(3,1)),
             'tris':np.array([[0,1,2]]),'uv':np.zeros((3,2)),'J':np.zeros((3,1),int),'jid':np.zeros(3,int),
             'tex':None,'color':(255,255,255,255)}]


def test_ninja_manual_geometry_is_attempted_intact_then_stops_on_native_rejection(tmp_path,monkeypatch):
    from gbox import re4gc_enemies as R,re6_models
    from PIL import Image
    prims=geometry();calls=[]
    monkeypatch.setattr(S,'load_rig',lambda *a:{})
    monkeypatch.setattr(S,'retarget',lambda *a,**k:(prims,{}))
    monkeypatch.setattr(S,'write_rigged',lambda *a:Path('rigged.gltf'))
    monkeypatch.setattr(S,'read_rigged',lambda *a:geometry())
    monkeypatch.setattr(R,'decimate',lambda *a:pytest.fail('No geometry reduction authorized'))
    monkeypatch.setattr(re6_models,'_pack',lambda *a:Image.new('RGB',(256,256)))
    monkeypatch.setattr(N,'split_nodes',lambda prims,tgt:{0:([],[],[1])})
    def reject(geo):calls.append(geo);raise ValueError('vertex cache capacity exceeded')
    with pytest.raises(ValueError,match='Automatic geometry reduction disabled: vertex cache'):
        N.fit(Path('donor'),{}, {'roles':{}},tmp_path,'manual',[0],None,reject,scale={'profile':{'preserve_geometry':True}})
    assert len(calls)==1


def test_doa2_keeps_the_native_chr_budget_error_without_calling_decimator(monkeypatch):
    from gbox import re4gc_enemies as R
    monkeypatch.setattr(R,'decimate',lambda *a:pytest.fail('No geometry reduction authorized'))
    def reject(*a,**k):raise ValueError('CHR budget exceeded: 1000 > 800')
    monkeypatch.setattr(D,'encode_parts',reject)
    with pytest.raises(ValueError,match='Automatic geometry reduction disabled: CHR budget exceeded'):
        D.encode_budgeted(b'',b'',geometry(),{}, {},800,preserve_geometry=True)


def test_ff7_preserves_the_manual_mesh_and_returns_the_allocation_failure(tmp_path,monkeypatch):
    from gbox import re4gc_enemies as R
    monkeypatch.setattr(F,'fit',lambda *a:(geometry(),{}))
    monkeypatch.setattr(S,'write_rigged',lambda *a:Path('rigged.gltf'))
    monkeypatch.setattr(S,'read_rigged',lambda *a:geometry())
    monkeypatch.setattr(R,'decimate',lambda *a:pytest.fail('No geometry reduction authorized'))
    def reject(geo):return b'',{'triangles':1,'bytes':900,'budget':800},False,.5
    with pytest.raises(ValueError,match='automatic geometry reduction disabled'):
        F._fit_loop('manual',{},Path('donor'),{},tmp_path,None,reject,0,lambda *a:None,
                    scale={'profile':{'preserve_geometry':True}})
