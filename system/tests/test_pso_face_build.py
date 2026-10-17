import hashlib
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import pso_face_build as F,pso_gc as G,pso_gc_swap as W


def gvr(color=(60,80,100,255),size=64):
    image=np.full((size,size,4),color,np.uint8)
    data=W.gx_encode(image,14)
    return b'GVRT'+struct.pack('<I',len(data)+8)+bytes([0,0,0,14])+struct.pack('>HH',size,size)+data


def afs(entries):
    data=bytearray(b'AFS\0'+struct.pack('<I',len(entries))+bytes(len(entries)*8))
    data+=bytes((-len(data))%0x800)
    for i,entry in enumerate(entries):
        struct.pack_into('<II',data,8+i*8,len(data),len(entry));data+=entry;data+=bytes((-len(data))%0x800)
    return bytes(data)


class Disc:
    def __init__(self,files):self.data=files;self.files={p:(0,len(b)) for p,b in files.items()}
    def read(self,path):return self.data[path]


def test_catalog_only_primary_face_maps_and_stable_identity(monkeypatch):
    raw=afs([gvr(),gvr((30,30,30,255)),gvr((40,40,40,255))])
    disc=Disc({'plAtex.afs':raw})
    monkeypatch.setattr(G,'tables',lambda disc:{'A':{'afs':['pxtAf_01a_w_kao1','pxtAf_01a_w_kao2','pxtAb_01a_w_body']}})
    rows=F.surface_catalog(disc)
    assert len(rows)==1 and rows[0]['kind']=='player' and rows[0]['class_name']=='HUmar'
    assert rows[0]['id']==F.surface_catalog(disc)[0]['id']
    assert F.read_surface(disc,rows[0]['id'])==gvr()
    assert rows[0]['profile']['geometry_changed'] is False
    assert not F._face_name('pxtAf_00b_t_mimi') and not F._face_name('i_32_npc_hair')
    assert F._face_name('i_64_hosa_face2')


def test_face_paint_keeps_header_size_format_and_distant_native_blocks():
    raw=gvr();profile=F.default_profile('A')
    profile['quad']=[[.35,.35],[.65,.35],[.65,.65],[.35,.65]]
    photo=Image.new('RGBA',(64,64),(230,100,60,255))
    after=F.paint(raw,photo,profile)
    assert len(after)==len(raw) and after[:16]==raw[:16] and after!=raw
    assert after[16:16+32]==raw[16:16+32]
    assert after[-32:]==raw[-32:]
    assert G.gvr_header(after)['fmt']==14


def test_afs_face_edit_does_not_repack_or_touch_ear_or_body_entries(monkeypatch):
    entries=[gvr(),gvr((20,30,40,255)),gvr((70,80,90,255))]
    raw=afs(entries);disc=Disc({'plAtex.afs':raw})
    monkeypatch.setattr(G,'tables',lambda disc:{'A':{'afs':['pxtAf_01a_w_kao1','pxtAf_01a_w_kao2','pxtAb_01a_w_body']}})
    files,coverage=F.patch_files(disc,Image.new('RGBA',(64,64),'white'))
    out=files['plAtex.afs'];parsed=G.afs(out)
    assert len(out)==len(raw) and out[:0x800]==raw[:0x800]
    assert parsed[0]!=entries[0] and parsed[1:]==entries[1:]
    assert len(coverage)==1 and coverage[0]['changed']


def test_android_profile_is_restricted_and_does_not_claim_human_head_conversion():
    p=F.default_profile('C',head=3,android=True)
    assert p['quad'][0][0]>=.3 and p['quad'][1][0]<=.7
    assert p['head']==3 and 'helmet' in p['scope'] and not p['alignment_verified_in_game']


def test_unknown_npc_model_reference_does_not_fabricate_a_player_mesh(tmp_path):
    path,info=F.export_surface_reference(None,{'model_binding':None},tmp_path)
    assert path is None and 'no verified exported model binding' in info['reason']


def test_palette_or_mipmapped_face_is_rejected_before_encode():
    raw=bytearray(gvr());raw[10]=1
    with pytest.raises(ValueError,match='Unsupported'):F.paint(bytes(raw),Image.new('RGBA',(32,32)),F.default_profile())


def gvm(entries):
    table=b''.join(struct.pack('>H',i)+name.encode().ljust(28,b'\0') for i,(name,_raw) in enumerate(entries))
    return b'GVMH'+struct.pack('<I',4+len(table))+struct.pack('>HH',8,len(entries))+table+b''.join(raw for _name,raw in entries)


def bml(body,texture):
    head=bytearray(0x800);struct.pack_into('>I',head,4,1)
    head[0x40:0x40+len(b'npc_body.nj')]=b'npc_body.nj'
    struct.pack_into('>5I',head,0x60,len(body),0,len(body),len(texture),len(texture))
    return bytes(head)+body+bytes(-len(body)%32)+texture+bytes(-len(texture)%32)


def gsl(entries):
    head=bytearray(0x800);data=bytearray()
    for i,(name,raw) in enumerate(entries):
        head[i*0x30:i*0x30+len(name)]=name.encode()
        struct.pack_into('>II',head,i*0x30+0x20,1+len(data)//0x800,len(raw))
        data+=raw+bytes(-len(raw)%0x800)
    return bytes(head+data)


def test_nested_npc_pack_patch_preserves_mesh_motion_unrelated_archive_and_gvr_header():
    face=gvr();hair=gvr((90,60,30,255));mesh=b'original model, rig and weights unchanged'
    pack=bml(mesh,gvm([('i_64_test_face',face),('i_32_test_hair',hair)]))
    area=gsl([('bm_npc_test.bml',pack),('unrelated.njm',b'original motion')])
    disc=Disc({'gsl_city.gsl':area})
    rows=F.surface_catalog(disc)
    assert len(rows)==1 and rows[0]['locator']['archive_entry']=='bm_npc_test.bml'
    assert rows[0]['model_binding']['archive_entry']=='bm_npc_test.bml'
    assert F.read_surface(disc,rows[0])==face
    files,coverage=F.patch_files(disc,Image.new('RGBA',(64,64),'white'))
    rebuilt=G.gsl_files(files['gsl_city.gsl']);body,textures=G.bml_entry(rebuilt['bm_npc_test.bml'],'npc_body.nj')
    assert body==mesh and rebuilt['unrelated.njm']==b'original motion'
    named=G.gvm_entries(textures)
    assert named[0][1]!=face and named[0][1][:16]==face[:16] and named[1][1]==hair
    assert coverage[0]['changed'] and not F.coverage_gaps(disc,coverage)


def test_saved_mask_shape_inset_and_erase_restore_strokes_are_applied():
    original=Image.new('RGBA',(64,64),(60,80,100,255));photo=Image.new('RGBA',(64,64),'white')
    profile=F.default_profile();profile.update(crop=[0,0,1,1],quad=[[0,0],[1,0],[1,1],[0,1]],feather=0)
    profile['mask']={'shape':'rectangle','inset':.2}
    before=F.paint_image(original,photo,profile)
    assert before.getpixel((4,4))==original.getpixel((4,4)) and before.getpixel((16,16))==(255,255,255,255)
    profile['strokes']=[{'x':.5,'y':.5,'radius':.2,'erase':True}]
    erased=F.paint_image(original,photo,profile)
    assert erased.getpixel((32,32))==original.getpixel((32,32))
    profile['strokes'].append({'x':.5,'y':.5,'radius':.04,'erase':False})
    restored=F.paint_image(original,photo,profile)
    assert restored.getpixel((32,32))==(255,255,255,255)
    assert restored.getpixel((24,32))==original.getpixel((24,32))


def test_explicit_npc_atlas_face_island_does_not_paint_other_body_regions():
    raw=gvr(size=256);profile=F._row({'kind':'afs','path':'plYtex.afs','index':2},'pxtYh_00z_t_head',raw,'Y')['profile']
    after=F.paint(raw,Image.new('RGBA',(64,64),'white'),profile)
    assert after[:16+32*20]==raw[:16+32*20] and after!=raw
    # NiGHTS has two disjoint face islands in a mixed clothing atlas.
    profile=F._row({'kind':'bml','path':'x','index':0},'s256_nights',raw)['profile']
    assert len(profile['additional_patches'])==1


def test_bad_mask_and_recursive_patches_are_rejected():
    original=Image.new('RGBA',(64,64));p=F.default_profile();p['mask']={'shape':'all'}
    with pytest.raises(ValueError,match='mask'):F.paint_image(original,original,p)
    p=F.default_profile();p['additional_patches']=[{'additional_patches':[{}]}]
    with pytest.raises(ValueError,match='eight'):F.paint_image(original,original,p)


def test_reference_head_uses_selected_face_variant_instead_of_default_skin(monkeypatch,tmp_path):
    from types import SimpleNamespace
    default,selected=gvr((40,50,60,255)),gvr((100,110,120,255))
    disc=Disc({'plAtex.afs':afs([default,selected])});disc.f=SimpleNamespace(name='fixture.iso');disc.game_id='GPOE8P'
    table={'afs_file':'plAtex.afs','afs':['pxtAf_01b_w_kao1','pxtAf_01a_w_kao1'],'heads':[['pxtAf_01b_w_kao1']]}
    monkeypatch.setattr(G,'tables',lambda view:{'A':table})
    def export(view,letter,out,head,hair=0):
        assert G.afs(view.read('plAtex.afs'))[0]==selected
        assert hair==3
        return tmp_path/'actual.glb',{'head':head,'textures':{100:'pxtAf_01b_w_kao1',101:'ear'}}
    monkeypatch.setattr(G,'export_player',export)
    row=F._row({'kind':'afs','path':'plAtex.afs','index':1},'pxtAf_01a_w_kao1',selected,'A','player',{'kind':'player','class_letter':'A'})
    model,info=F.export_surface_reference(disc,row,tmp_path,hair=3)
    assert model.name=='actual.glb' and info['reference_face_surface']==row['id']
    assert info['reference_face_materials']==['tex100']
    assert G.afs(disc.read('plAtex.afs'))==[default,selected]


def test_native_humanoid_eye_line_and_hucaseal_head_profiles_are_distinct():
    human=F.default_profile('B');caseal=F.default_profile('F',android=True)
    assert human['quad'][0][1]>.1 and caseal['quad']==human['quad']
    assert len({str(F.default_profile('J',head,True)['quad']) for head in range(5)})==5
    assert F.default_profile('D')['quad'][0][1]<.02
    assert F._row({'kind':'gvm','path':'npc.gvm','index':0},'i_64_npc_face',gvr())['class_name'] is None


def test_portable_originals_use_one_archive_with_bounded_stable_entries(tmp_path):
    import zipfile
    source={'a'*24:gvr(),'b'*24:gvr((90,80,70,255))}
    target=F.write_originals(tmp_path,source)
    assert [p.name for p in tmp_path.iterdir()]==['face-originals.zip']
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist()==['a'*24+'.gvr','b'*24+'.gvr']
        assert all(archive.read(key+'.gvr')==raw for key,raw in source.items())
    with pytest.raises(FileExistsError):F.write_originals(tmp_path,source)


def test_original_archive_rejects_traversal_and_oversized_entries_before_writing(tmp_path):
    for source in ({'../escape':gvr()},{'a'*24:bytes(F.MAX_ORIGINAL+1)}):
        with pytest.raises(ValueError,match='Invalid or oversized'):F.write_originals(tmp_path,source)
    assert not list(tmp_path.iterdir())


def test_native_paint_rejects_truncated_and_oversized_payload_before_decode(monkeypatch):
    raw=gvr();oversized=bytearray(raw);struct.pack_into('>H',oversized,12,2048)
    monkeypatch.setattr(G,'gvr_decode',lambda raw:pytest.fail('Unbounded/truncated payload reached native decoder'))
    with pytest.raises(ValueError,match='payload'):F.paint(raw[:-1],Image.new('RGBA',(64,64)),F.default_profile())
    with pytest.raises(ValueError,match='oversized'):F.paint(bytes(oversized),Image.new('RGBA',(64,64)),F.default_profile())
