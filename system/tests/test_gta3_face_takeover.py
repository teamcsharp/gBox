"""Native face UV projection, body preservation and original palette invariants."""
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import gta_rw as R,gta3_face_takeover as F


def raster(width=32,height=32):
    palette=np.zeros((256,4),np.uint8);palette[:,0]=np.arange(256);palette[:,1]=np.arange(256);palette[:,2]=np.arange(256);palette[:,3]=128
    native=np.empty_like(palette);native[R._csm1(256)]=palette
    header=struct.pack('<16I',width,height,8,0x2504,0,0,0,0,0,0,0,0,width*height,1024,0,0)
    return R.Ps2Raster('face','',width,height,8,0x2504,header,bytes([10])*(width*height)+native.tobytes())


def face_surface(head=True):
    return {'head':head,'frame':'Shead' if head else 'Storso',
        'pos':np.array([[-1,0,0],[1,0,0],[1,0,2],[-1,0,2]],float),
        'nrm':np.tile([0,1,0],(4,1)), 'uv':np.array([[.2,.8],[.8,.8],[.8,.2],[.2,.2]]),
        'tris':np.array([[0,1,2],[0,2,3]]),'mat':np.array([0,0]),'textures':['face']}


def test_head_projection_preserves_body_regions_and_alpha():
    original=np.full((32,32,4),[10,20,30,255],np.uint8)
    body=face_surface(False);body['uv']=np.array([[.2,.8],[.4,.8],[.4,.2],[.2,.2]])
    painted,mask,report=F.project_face(original,[face_surface(),body],'face',Image.new('RGB',(80,100),'white'),[0,0,1,1])
    assert report['face_pixels']>20 and report['protected_body_pixels']>0
    assert np.array_equal(painted[~mask],original[~mask])
    assert np.array_equal(painted[...,3],original[...,3])
    assert not mask[:,:12].any()
    assert np.any(painted[mask,:3]!=original[mask,:3])


def test_native_index_writes_preserve_palette_header_and_unmasked_pixels():
    native=raster();before=R.raster_rgba(native)
    mask=np.zeros((32,32),bool);mask[8:24,10:20]=True
    painted=before.copy();painted[mask,:3]=210
    new,mips=F.raster_projected(native,painted,mask)
    assert new.header==native.header and len(new.data)==len(native.data)
    assert new.data[1024+int(R._csm1(256)[10])*4:1024+int(R._csm1(256)[10])*4+4]==native.data[1024+int(R._csm1(256)[10])*4:1024+int(R._csm1(256)[10])*4+4]
    assert np.array_equal(R.raster_rgba(new)[~mask],before[~mask])
    assert R.raster_rgba(new)[mask,:3].mean()>200
    assert mips[0]['changed_bytes']==mask.sum()


def test_uv_seam_rasterization_does_not_stretch_across_the_entire_atlas():
    seen=np.zeros((32,32),bool)
    for yy,xx,bary in F.raster_triangle([[.98,.4],[1.02,.4],[1.02,.6]],32,32):
        seen[yy,xx]=True
        assert np.allclose(bary.sum(1),1)
    assert seen.any() and not seen[:,4:28].any()


def test_backward_head_and_fully_shared_body_uv_are_refused():
    original=np.full((32,32,4),255,np.uint8);surface=face_surface();surface['nrm']*=-1
    with pytest.raises(ValueError,match='No usable'):F.project_face(original,[surface],'face',Image.new('RGB',(10,10)),[0,0,1,1])
    with pytest.raises(ValueError,match='No usable'):F.project_face(original,[face_surface(),face_surface(False)],'face',Image.new('RGB',(10,10)),[0,0,1,1])


def test_wrong_base_image_rejected_before_creating_build(tmp_path):
    from gbox.config import Config
    path=tmp_path/'source.iso';path.write_bytes(b'not an owned disc')
    with pytest.raises(ValueError,match='exact owned'):F.build(Config(cache_dirs={'windows':str(tmp_path/'cache'),'linux':str(tmp_path/'cache')}),path,Image.new('RGB',(10,10)),'a'*64,'test')
    assert not (tmp_path/'cache').exists()


def test_nonfacial_head_uv_aliases_are_protected():
    original=np.full((32,32,4),[10,20,30,255],np.uint8)
    back=face_surface();back['nrm']*=-1
    back['uv']=np.array([[.2,.8],[.4,.8],[.4,.2],[.2,.2]])
    painted,mask,report=F.project_face(original,[face_surface(),back],'face',Image.new('RGB',(20,20),'white'),[0,0,1,1])
    assert report['protected_nonfacial_head_pixels']>0
    assert not mask[:,:12].any()
    assert np.array_equal(painted[~mask],original[~mask])


def test_compact_contact_sheets_preserve_originals_and_bound_download_file_count(tmp_path):
    source=tmp_path/'exhaustive';dest=tmp_path/'.final-staging';rows=[]
    for name in ('player','cop','eight','pedestrian'):
        folder=source/'previews'/name;folder.mkdir(parents=True)
        row={'model':name+'.dff','face_previews':[{'texture':'face'}],'face_snapshots':[]}
        for label in ('before','after','mask'):
            path=folder/(label+'.png');Image.new('RGB',(32,32),'blue').save(path)
            row['face_previews'][0][label]=path.relative_to(source).as_posix()
        for fraction in (0,.25,.5,.75,1):
            path=folder/('head-'+str(fraction)+'.png');Image.new('RGB',(32,32),'red').save(path)
            row['face_snapshots'].append({'fraction':fraction,'path':path.relative_to(source).as_posix()})
        rows.append(row)
    before=list(source.rglob('*.png'))
    result=F.compact_previews(source,dest,rows)
    assert len(list(source.rglob('*.png')))==len(before)==32
    assert len(list(dest.rglob('*.png')))==32 # 3 standalone stories x 8 + 8 complete sheets
    assert result['complete_actors']==4
    assert rows[-1]['face_snapshots'][-1]['rect']==[384,32,128,128]
    assert (dest/rows[-1]['face_snapshots'][-1]['path']).is_file()
    with pytest.raises(ValueError,match='unpublished'):F.compact_previews(source,source,rows)
