import gzip,struct
import numpy as np
import pytest
from gbox import ff7_field_textures as T,ff7_models as F,ff7_swap as S


def test_optimal_lzss_fits_more_detail_without_changing_decoded_asset():
    import random
    from gbox.formats.lz import lzss_compress,lzss_compress_optimal,lzss_decompress
    randomizer=random.Random(918)
    for data in (b'',b'abc',b'\0'*9000,bytes(randomizer.randrange(4) for _ in range(2000)),bytes(range(256))*25):
        encoded=lzss_compress_optimal(data)
        assert lzss_decompress(encoded)[0]==data
        assert len(encoded)<=len(lzss_compress(data))
    with pytest.raises(ValueError,match='one MiB'):lzss_compress_optimal(bytes(1_048_577))


def native_files(shared=False):
    images=16;palettes=34;palette_at=16+images*512
    tdb=bytearray(palette_at+palettes*32)
    struct.pack_into('<IHHII',tdb,0,len(tdb),images,palettes,16,palette_at)
    module=bytearray(T.MOUTHS+T.FACES*3+1)
    for face in range(T.FACES):
        module[T.EYES+7*face:T.EYES+7*face+7]=bytes([15])*7
        module[T.MOUTHS+3*face:T.MOUTHS+3*face+3]=bytes([15])*3
    module[T.EYES:T.EYES+7]=bytes([15,0,1,2,3,4,7])
    module[T.MOUTHS:T.MOUTHS+3]=bytes([15,5,6])
    if shared:module[T.EYES+7]=0
    compressed=gzip.compress(bytes(module),mtime=0)
    return S.lzs_encode(bytes(tdb))+bytes(4096),struct.pack('<II',len(module),len(compressed))+compressed+bytes(2048),tdb,module


def primitive():
    texture=np.full((32,32,4),255,np.uint8)
    texture[8:24,8:24,:3]=(0,0,0)
    texture[:4,:4,3]=0
    return {'tex':texture,'color':(255,255,255,255),'uv':np.array([[0,0],[1,0],[.5,.5],[1.25,-.5]])}


def test_atlas_preserves_other_faces_and_code_and_keeps_interior_detail():
    tdb,module,raw_tdb,raw_module=native_files();p=primitive()
    atlas=T.FieldAtlas(tdb,module,[p])
    changed=F.lzs(atlas.tdb);new_module=gzip.decompress(atlas.field[8:])
    image_start=16;palette_at=16+16*512
    allowed=set(range(image_start,image_start+512))|set(range(image_start+5*512,image_start+6*512))|set(range(palette_at,palette_at+32))
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(raw_tdb,changed)))
    code_allowed=set(range(T.EYES,T.EYES+7))|set(range(T.MOUTHS,T.MOUTHS+3))
    assert all(a==b or i in code_allowed for i,(a,b) in enumerate(zip(raw_module,new_module)))
    assert new_module[T.EYES:T.EYES+7]==bytes(7)
    assert new_module[T.MOUTHS:T.MOUTHS+3]==bytes([5])*3
    assert atlas.pages[0][0,0,3]==0
    assert (atlas.pages[0][8,16]==[0,0,0,255]).all(),'interior opaque black detail survives, unlike corner-color baking'
    assert len(atlas.tdb)==len(tdb) and len(atlas.field)==len(module),'the full original allocation must be overwritten to clear stale compressed tails'
    assert atlas.report['static_expressions']
    readback=T.face_tim(atlas.tdb,atlas.field)
    assert np.array_equal(F.tim_rgba(readback,0)[:32,:32],atlas.pages[0])
    assert np.array_equal(F.tim_rgba(readback,0)[160:192,:32],atlas.pages[1])
    page,uv=atlas.uv(p,[0,1,2]);assert page==0 and uv==[(0,0),(31,0),(16,8)]
    assert atlas.uv(p,[3])[1]==[(8,8)]


def test_shared_face_bank_is_refused_and_sources_are_immutable():
    tdb,module,_,_=native_files(shared=True)
    before=(tdb,module)
    with pytest.raises(ValueError,match='shared'):T.FieldAtlas(tdb,module,[primitive()])
    assert (tdb,module)==before


def test_more_than_eight_maps_is_refused_instead_of_silently_losing_detail():
    tdb,module,_,_=native_files();prims=[]
    for i in range(9):
        p=primitive();p['color']=(i,255,255,255);prims.append(p)
    with pytest.raises(ValueError,match='allocation'):T.FieldAtlas(tdb,module,prims)


def test_unrecognized_field_code_layout_cannot_be_patched():
    tdb,module,_,raw=native_files();raw[T.EYES+2]=9
    compressed=gzip.compress(bytes(raw),mtime=0)
    altered=struct.pack('<II',len(raw),len(compressed))+compressed+bytes(2048)
    with pytest.raises(ValueError,match='expression table'):T.FieldAtlas(tdb,altered,[primitive()])


def test_native_field_packet_roundtrip_keeps_uvs_descriptors_and_buffer_budget():
    raw=bytearray(148);header=64;skeleton=96
    struct.pack_into('<II',raw,0,len(raw),header);raw[header+2:header+5]=bytes([1,1,1])
    struct.pack_into('<3H',raw,header+0x16,4096,4,36)
    struct.pack_into('<I',raw,header+0x1c,skeleton|0x80000000)
    struct.pack_into('<hBB',raw,skeleton,0,255,1)
    struct.pack_into('<HBBBBHHHI',raw,132,1,0,0,0,0,0,0,0,32|0x80000000)
    fm={'raw':bytes(raw),'skeleton':skeleton,'parts_off':4,'anims_off':36,'header':header,'anims':[[]],
        'parts':[{'bone':0,'raw':bytes(32),'buffer':1000}]}
    geo={0:{'verts':[(0,0,0),(10,0,0),(0,10,0)],'nrm':np.array([[0,0,1]]*3),
         'tris':[((0,1,2),((80,90,100),)*3)],'quads':[],
         'field_tex_tris':[((0,2,1),[(0,160),(31,175),(15,190)],1)]}}
    rebuilt,report=S.write_field(fm,geo,np.array([[0,0,1]]*240),1)
    parsed=F.read_field_model(rebuilt,compressed=False);part=parsed['parts'][0]
    assert part['counts']['tct']==1 and part['counts']['tc']==1
    assert part['ntc']==3 and part['flags']==2 and part['controls']==1
    assert report['gpu_buffer']==part['buffer']==68
    assert report['textured_triangles']==1 and report['triangles']==2
    assert part['polys'][0]['tc']==[0,1,2]
    assert rebuilt[part['ovx']+part['otc']:part['ovx']+part['octl']]==bytes([0,160,31,175,15,190])
    assert struct.unpack_from('<2I',rebuilt,part['ovx']+part['ofl'])==(0x78141c00,0x78141c01)
    assert rebuilt[part['ovx']+part['octl']]==1
    parsed['tim']={'native':'fixture'}
    converted=F.field_to_battle_dict(parsed)
    mesh=converted['bones'][0]['mesh']
    assert mesh['tt']==[([0,2,1],[(0,160),(31,175),(15,190)],0x7814)]
    assert mesh['tt_page']==28 and converted['tim']==parsed['tim']
