import numpy as np
import pytest
from PIL import Image
from gbox.native_face_projection import project


def quad(v_offset=0):
    return {'pos':np.array([[-1,1,1],[1,1,1],[1,-1,1],[-1,-1,1]]),
            'nrm':np.tile([0,0,1],(4,1)),'uv':np.array([[.25,.25],[.75,.25],[.75,.75],[.25,.75]])+[0,v_offset],
            'tris':np.array([[0,1,2],[0,2,3]])}


def test_projection_preserves_outside_alpha_and_geometry():
    base=np.full((32,32,4),[40,50,60,127],np.uint8);photo=Image.new('RGB',(8,8),(200,10,20));p=quad();before={k:v.copy() for k,v in p.items()}
    out=project(Image.fromarray(base),photo,[p]);arr=np.asarray(out.image)
    assert out.report['masked_pixels']>60
    assert np.array_equal(arr[out.mask==0],base[out.mask==0])
    assert np.array_equal(arr[...,3],base[...,3])
    assert all(np.array_equal(before[k],p[k]) for k in p)


def test_negative_repeat_uv_matches_positive_without_seam_tearing():
    base=Image.new('RGBA',(32,32),(1,2,3,255));photo=Image.new('RGBA',(8,8),(190,30,20,255))
    a=project(base,photo,[quad()]);b=project(base,photo,[quad(-1)])
    assert np.array_equal(a.image,b.image)


def test_uv_uses_native_geometry_orientation_and_crop():
    photo=np.zeros((8,8,4),np.uint8);photo[:,:,:]=[255,0,0,255];photo[:,4:]=[0,0,255,255]
    out=project(Image.new('RGBA',(32,32),(0,0,0,255)),Image.fromarray(photo),[quad()],feather=.1)
    assert np.asarray(out.image)[16,12,2]>150
    assert np.asarray(out.image)[16,20,0]>150


def test_front_filter_rejects_back_surfaces():
    p=quad();p['nrm']*=-1
    out=project(Image.new('RGBA',(32,32)),Image.new('RGB',(8,8),'red'),[p])
    assert out.report['masked_pixels']==0


def test_native_gloss_alpha_can_be_preserved_without_punching_rgb_holes():
    base=np.full((32,32,4),[40,50,60,0],np.uint8)
    out=project(Image.fromarray(base),Image.new('RGB',(8,8),'red'),[quad()],respect_alpha=False)
    arr=np.asarray(out.image)
    assert arr[16,16,0]>200 and np.array_equal(arr[...,3],base[...,3])


def test_native_mirrored_uvs_sample_one_consistent_photo_half():
    p=quad();p['pos']=p['pos'].astype(float);p['pos'][:,0]=(p['pos'][:,0]+1)*.5
    q={k:v.copy()for k,v in p.items()};q['pos'][:,0]*=-1;q['pos'][:,2]+=1e-12
    photo=np.zeros((16,16,4),np.uint8);photo[:]=[255,0,0,255];photo[:,8:]=[0,0,255,255]
    base=Image.new('RGBA',(32,32),(0,0,0,255));kwargs={'bounds':[-1,-1,1,1],'mirror_x':True}
    one=project(base,Image.fromarray(photo),[p],**kwargs)
    both=project(base,Image.fromarray(photo),[p,q],**kwargs)
    assert np.array_equal(one.image,both.image)


def test_transparent_source_rgb_is_not_painted_into_a_native_face():
    original=Image.new('RGBA',(32,32),(40,50,60,255))
    out=project(original,Image.new('RGBA',(8,8),(255,0,0,0)),[quad()])
    assert np.array_equal(original,out.image) and out.report['masked_pixels']==0


@pytest.mark.parametrize('crop',[(1,0,0,1),(-.1,0,1,1),(0,0,2,1),(0,0,float('nan'),1)])
def test_invalid_crop_rejected(crop):
    with pytest.raises(ValueError):project(Image.new('RGBA',(8,8)),Image.new('RGB',(8,8)),[quad()],crop=crop)
