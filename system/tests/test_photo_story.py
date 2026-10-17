import io
import numpy as np
import pytest
from PIL import Image
from gbox import photo_story as S,photo_skin as P,characters as C


def fixture():
    before=Image.new('RGBA',(8,8),(20,40,200,255));after=Image.new('RGBA',(8,8),(220,40,20,255))
    xyz=np.asarray([[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],float)
    uv=np.asarray([[0,1],[1,1],[1,0],[0,0]],float)
    triangles=[(xyz[t],uv[t],np.asarray(before),np.asarray([255,255,255])) for t in ([0,1,2],[0,2,3])]
    return before,after,triangles


def test_recorded_frames_preserve_geometry_camera_and_match_real_texture_endpoints():
    before,after,triangles=fixture();copy=[t[0].copy() for t in triangles]
    frames=S.render_frames(triangles,[(before,after)],[[0,0],[1,0],[1,1],[0,1]],size=80)
    assert [f for f,_ in frames]==[0,.25,.5,.75,1]
    images=[Image.open(io.BytesIO(data)) for _,data in frames]
    assert images[0].getpixel((40,40))==(20,40,200,255)
    assert images[-1].getpixel((40,40))==(220,40,20,255)
    assert images[2].getpixel((40,40))==(120,40,110,255)
    assert all(np.array_equal(a,t[0]) for a,t in zip(copy,triangles))


def test_no_mesh_unknown_uv_or_excessive_geometry_cannot_create_fake_snapshots():
    before,after,triangles=fixture()
    with pytest.raises(ValueError):S.render_frames([],[(before,after)],[[0,0],[1,0],[1,1],[0,1]])
    with pytest.raises(ValueError):S.render_frames(triangles,[(after,before)],[[0,0],[1,0],[1,1],[0,1]])
    with pytest.raises(ValueError):S.render_frames(triangles*25001,[(before,after)],[[0,0],[1,0],[1,1],[0,1]])


def test_photo_approval_keeps_recorded_story_with_the_approved_variant(api,monkeypatch):
    c,store,root,photo=api
    story={'schema':1,'geometry':'unchanged','source_photo':photo,'frames':[]}
    monkeypatch.setattr(S,'record',lambda *a,**kw:story)
    review=c.post('/api/characters/base/photo-skins',json={'photo':photo,'maps':[0]}).json()
    assert review['story']==story
    accepted=c.post('/api/photo-skins/'+review['id']+'/decision',json={'decision':'accept'}).json()
    assert C.get(root,accepted['variant'])['photo_skin_approval']['story']==story


from tests.test_photo_skin import api
